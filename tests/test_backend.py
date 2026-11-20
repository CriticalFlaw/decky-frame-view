"""Backend tests.

Unit tests run anywhere. The end-to-end tests need an SSH server that stands in
for the Frame; set FRAMEVIEW_TEST_HOST / _PORT / _USER / _PASSWORD to run them
(see README.md, Development). Run with:  python3 -m unittest discover -s tests
"""

import asyncio
import os
import sys
import tempfile
import unittest
import urllib.request
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from frameview import remote  # noqa: E402
from frameview.core import Core  # noqa: E402
from frameview.server import StreamServer  # noqa: E402


class RemoteTests(unittest.TestCase):
    def test_host_validation(self):
        for good in ("frame.local", "frame", "192.168.1.20", "fe80::1", "my-frame.lan"):
            self.assertEqual(remote.check_host(good), good)
        for bad in ("", "-oProxyCommand=x", "a b", "frame;rm", "$(id)"):
            with self.assertRaises(remote.RemoteError):
                remote.check_host(bad)

    def test_user_validation(self):
        self.assertEqual(remote.check_user("steamos"), "steamos")
        for bad in ("", "-l", "root@x", "a b"):
            with self.assertRaises(remote.RemoteError):
                remote.check_user(bad)

    def test_stream_command(self):
        cmd = remote.stream_command("h264", 720, 30)
        self.assertIn("/dev/video99", cmd)
        self.assertIn("libx264", cmd)
        self.assertIn("aud=1:repeat-headers=1", cmd)
        self.assertIn("scale=-2:720", cmd)
        self.assertIn("cat >/dev/null", cmd)
        self.assertIn("-f mjpeg", remote.stream_command("mjpeg", 480, 60))
        with self.assertRaises(remote.RemoteError):
            remote.stream_command("vp9", 720, 30)
        with self.assertRaises(remote.RemoteError):
            remote.stream_command("h264", 721, 30)

    def test_probe_parse(self):
        info = remote.parse_probe("device=yes\nffmpeg=yes\nsteamvr=no\nhost=frame\n")
        self.assertEqual(info, {"device": True, "ffmpeg": True, "steamvr": False, "hostname": "frame"})

    def test_ssh_failure_messages(self):
        self.assertIn("Pair again", remote.describe_ssh_failure(255, "steamos@frame: Permission denied (publickey)."))
        self.assertIn("Developer Mode", remote.describe_ssh_failure(255, "connect to host x port 22: Connection refused"))

    def test_clean_env_drops_pyinstaller_libs(self):
        old = dict(os.environ)
        try:
            os.environ["LD_LIBRARY_PATH"] = "/tmp/_MEI123"
            os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
            self.assertNotIn("LD_LIBRARY_PATH", remote.clean_env())
            os.environ["LD_LIBRARY_PATH_ORIG"] = "/opt/lib"
            self.assertEqual(remote.clean_env()["LD_LIBRARY_PATH"], "/opt/lib")
        finally:
            os.environ.clear()
            os.environ.update(old)


def _get(url, timeout=30):
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return r.status, r.headers, r
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_and_relay(self):
        async def factory(codec, h, fps):
            return [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 100000); sys.stdout.flush()"]

        srv = StreamServer(factory)
        port = await srv.start()
        base = f"http://127.0.0.1:{port}"
        loop = asyncio.get_running_loop()

        status, _, _ = await loop.run_in_executor(None, _get, f"{base}/stream?token=nope")
        self.assertEqual(status, 403)

        def read_all():
            status, headers, r = _get(f"{base}/stream?token={srv.token}&codec=h264&h=720&fps=30")
            return status, headers, r.read()

        status, headers, body = await loop.run_in_executor(None, read_all)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(body, b"x" * 100000)
        await srv.close()

    async def test_error_when_no_video(self):
        async def factory(codec, h, fps):
            return [sys.executable, "-c", "import sys; sys.stderr.write('The headset view device (/dev/video99) is missing. Is SteamVR running on the Frame?\\n'); sys.exit(3)"]

        srv = StreamServer(factory)
        port = await srv.start()
        loop = asyncio.get_running_loop()

        def read():
            status, _, r = _get(f"http://127.0.0.1:{port}/stream?token={srv.token}")
            return status, json.loads(r.read())

        status, body = await loop.run_in_executor(None, read)
        self.assertEqual(status, 502)
        self.assertIn("SteamVR", body["error"])
        await srv.close()


@unittest.skipUnless(os.environ.get("FRAMEVIEW_TEST_HOST"), "set FRAMEVIEW_TEST_HOST for end-to-end tests")
class EndToEnd(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "settings"), os.path.join(self.tmp.name, "runtime"))
        self.core.update_settings({
            "host": os.environ["FRAMEVIEW_TEST_HOST"],
            "port": int(os.environ.get("FRAMEVIEW_TEST_PORT", "22")),
            "user": os.environ.get("FRAMEVIEW_TEST_USER", "steamos"),
        })

    async def asyncTearDown(self):
        await self.core.close()
        self.tmp.cleanup()

    async def test_pair_probe_and_stream(self):
        r = await self.core.test_connection()
        self.assertFalse(r["ok"])

        r = await self.core.pair("definitely-wrong")
        self.assertFalse(r["ok"], r)
        self.assertIn("password", r["message"].lower())

        r = await self.core.pair(os.environ["FRAMEVIEW_TEST_PASSWORD"])
        self.assertTrue(r["ok"], r)
        r = await self.core.pair(os.environ["FRAMEVIEW_TEST_PASSWORD"])  # idempotent
        self.assertTrue(r["ok"], r)

        r = await self.core.test_connection()
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["ffmpeg"])

        info = await self.core.stream_info()
        loop = asyncio.get_running_loop()
        for codec, marker in (("h264", b"\x00\x00\x00\x01\x09"), ("mjpeg", b"\xff\xd8")):
            def read():
                status, _, r = _get(f"{info['base']}/stream?token={info['token']}&codec={codec}&h=480&fps=30")
                return status, r.read(200_000)

            status, data = await loop.run_in_executor(None, read)
            self.assertEqual(status, 200, data[:300])
            self.assertTrue(data.startswith(marker) or marker in data[:64], data[:32])
            await self.core.stop_stream()


if __name__ == "__main__":
    unittest.main()
