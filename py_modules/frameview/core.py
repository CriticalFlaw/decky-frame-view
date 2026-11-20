"""Settings, the plugin's SSH key, pairing and the connection check.

Kept free of the ``decky`` module so it can be tested on any Linux machine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import stat
import tempfile

from . import remote
from .server import StreamServer

log = logging.getLogger("frameview")

DEFAULTS = {
    "host": "frame.local",
    "user": "steamos",
    "port": 22,
    "height": 720,
    "fps": 30,
    "codec": "auto",  # auto | h264 | mjpeg
}

ASKPASS = "#!/bin/sh\nprintf '%s\\n' \"$FRAMEVIEW_PASSWORD\"\n"


class Core:
    def __init__(self, settings_dir: str, runtime_dir: str, home: str | None = None):
        self.settings_dir = settings_dir
        self.runtime_dir = runtime_dir
        self.home = home
        os.makedirs(settings_dir, exist_ok=True)
        os.makedirs(runtime_dir, exist_ok=True)
        self.settings_path = os.path.join(settings_dir, "settings.json")
        self.key_path = os.path.join(settings_dir, "id_ed25519")
        self.known_hosts = os.path.join(settings_dir, "known_hosts")
        self.ssh = remote.SSH(self.key_path, self.known_hosts, shutil.which("ssh") or "/usr/bin/ssh")
        self.settings = self._load()
        self.server = StreamServer(self._stream_argv, self.env)

    # ---- settings -----------------------------------------------------------

    def _load(self) -> dict:
        data = dict(DEFAULTS)
        try:
            with open(self.settings_path) as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("Couldn't read settings; using defaults")
        return data

    def _save(self):
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.settings, f, indent=2)
        os.replace(tmp, self.settings_path)

    def public_settings(self) -> dict:
        return {
            **self.settings,
            "paired_key": os.path.exists(self.key_path),
            "public_key": self.public_key(),
        }

    def update_settings(self, changes: dict) -> dict:
        new = dict(self.settings)
        for key, value in (changes or {}).items():
            if key not in DEFAULTS:
                continue
            if key == "host":
                value = remote.check_host(value)
            elif key == "user":
                value = remote.check_user(value)
            elif key == "port":
                value = remote.check_port(value)
            elif key == "height":
                value = int(value)
                if value not in remote.HEIGHTS:
                    raise remote.RemoteError(f"Resolution must be one of {remote.HEIGHTS}")
            elif key == "fps":
                value = int(value)
                if value not in remote.FPS:
                    raise remote.RemoteError(f"Frame rate must be one of {remote.FPS}")
            elif key == "codec":
                if value not in ("auto", *remote.CODECS):
                    raise remote.RemoteError("Codec must be auto, h264 or mjpeg")
            new[key] = value
        self.settings = new
        self._save()
        return self.public_settings()

    # ---- processes ----------------------------------------------------------

    def env(self) -> dict:
        return remote.clean_env(self.home)

    async def _run(self, argv, *, stdin: bytes | None = None, env=None, timeout: float = 20):
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env or self.env(),
            start_new_session=True,  # no controlling terminal: ssh uses SSH_ASKPASS
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return 255, "", "Connection timed out"
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")

    # ---- key ----------------------------------------------------------------

    def public_key(self) -> str:
        try:
            with open(self.key_path + ".pub") as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""

    async def ensure_key(self) -> str:
        if os.path.exists(self.key_path) and self.public_key():
            return self.public_key()
        for p in (self.key_path, self.key_path + ".pub"):
            if os.path.exists(p):
                os.remove(p)
        keygen = shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"
        comment = f"decky-frame-view@{socket.gethostname()}"
        code, _, err = await self._run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", self.key_path])
        if code != 0:
            raise remote.RemoteError(f"Couldn't create an SSH key: {err.strip() or code}")
        os.chmod(self.key_path, 0o600)
        return self.public_key()

    def forget_host_key(self) -> dict:
        try:
            os.remove(self.known_hosts)
        except FileNotFoundError:
            pass
        return {"ok": True, "message": "Forgot the headset's identity. Pair again to reconnect."}

    # ---- pairing ------------------------------------------------------------

    async def pair(self, password: str) -> dict:
        """Install this Deck's key on the Frame using the Developer Mode password, once."""
        s = self.settings
        if not password:
            return {"ok": False, "message": "Enter the password you set in the Frame's Developer settings."}
        try:
            pub = await self.ensure_key()
            argv = self.ssh.command(s["host"], s["user"], s["port"], remote.INSTALL_KEY_COMMAND, batch=False)
        except remote.RemoteError as e:
            return {"ok": False, "message": str(e)}

        fd, askpass = tempfile.mkstemp(prefix="askpass-", dir=self.runtime_dir)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(ASKPASS)
            os.chmod(askpass, stat.S_IRWXU)
            env = self.env()
            env.update({
                "SSH_ASKPASS": askpass,
                "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": env.get("DISPLAY") or ":0",
                "FRAMEVIEW_PASSWORD": password,
            })
            code, out, err = await self._run(argv, stdin=(pub + "\n").encode(), env=env, timeout=30)
        finally:
            try:
                os.remove(askpass)
            except FileNotFoundError:
                pass
        if code != 0 or "paired" not in out:
            if "permission denied" in err.lower():
                return {"ok": False, "message": "Wrong password, or the Frame doesn't allow password logins."}
            return {"ok": False, "message": remote.describe_ssh_failure(code, err)}
        check = await self.test_connection()
        if not check["ok"]:
            return check
        return {**check, "message": "Paired. " + check["message"]}

    async def test_connection(self) -> dict:
        s = self.settings
        if not os.path.exists(self.key_path):
            return {"ok": False, "message": "Not paired yet. Pair with the Frame first."}
        try:
            argv = self.ssh.command(s["host"], s["user"], s["port"], remote.PROBE_COMMAND)
        except remote.RemoteError as e:
            return {"ok": False, "message": str(e)}
        code, out, err = await self._run(argv, timeout=20)
        if code != 0:
            return {"ok": False, "message": remote.describe_ssh_failure(code, err)}
        info = remote.parse_probe(out)
        name = info["hostname"] or s["host"]
        if not info["ffmpeg"]:
            msg = f"Connected to {name}, but ffmpeg isn't installed there."
            ok = False
        elif not info["device"]:
            msg = f"Connected to {name}. Start SteamVR on the Frame to see its view."
            ok = True
        else:
            msg = f"Connected to {name}. Ready to view."
            ok = True
        return {"ok": ok, "message": msg, **info}

    # ---- streaming ----------------------------------------------------------

    async def _stream_argv(self, codec: str, height: int, fps: int) -> list:
        s = self.settings
        if not os.path.exists(self.key_path):
            raise remote.RemoteError("Not paired yet. Pair with the Frame first.")
        return self.ssh.command(s["host"], s["user"], s["port"], remote.stream_command(codec, height, fps))

    async def stream_info(self) -> dict:
        if self.server.port is None:
            await self.server.start()
        s = self.settings
        return {
            "base": f"http://127.0.0.1:{self.server.port}",
            "token": self.server.token,
            "height": s["height"],
            "fps": s["fps"],
            "codec": s["codec"],
        }

    async def stop_stream(self) -> bool:
        await self.server.stop_stream()
        return True

    async def close(self):
        await self.server.close()
