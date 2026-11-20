"""A small loopback HTTP server that relays the Frame's video to the Steam UI.

The plugin's frontend runs inside Steam's browser, so it fetches
``http://127.0.0.1:<port>/stream?...`` and decodes the bytes itself
(WebCodecs for H.264, ``createImageBitmap`` for MJPEG). The server only
listens on loopback and every request must carry a random token that the
frontend gets from the plugin backend.

One viewer at a time: a new stream ends the previous one, just as reopening
the viewer should.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Awaitable, Callable, Optional
from urllib.parse import parse_qs, urlsplit

from . import remote

log = logging.getLogger("frameview")

FIRST_BYTES_TIMEOUT = 20.0  # seconds to wait for the first video bytes
STALL_TIMEOUT = 10.0  # seconds without bytes before a running stream is dropped
CHUNK = 64 * 1024
STDERR_LIMIT = 8 * 1024

CONTENT_TYPES = {"h264": "video/h264", "mjpeg": "application/octet-stream"}

# (codec, height, fps) -> argv of the process that writes the stream to stdout.
CommandFactory = Callable[[str, int, int], Awaitable[list]]


class StreamServer:
    def __init__(self, command_factory: CommandFactory, env_factory: Callable[[], dict] = lambda: None):
        self.command_factory = command_factory
        self.env_factory = env_factory
        self.token = secrets.token_urlsafe(24)
        self.port: Optional[int] = None
        self._server: Optional[asyncio.base_events.Server] = None
        self._current: Optional[asyncio.subprocess.Process] = None
        self._current_task: Optional[asyncio.Task] = None
        self.viewer_count = 0

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        self._server = await asyncio.start_server(self._handle, host, port)
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("Stream server listening on %s:%s", host, self.port)
        return self.port

    async def close(self):
        await self.stop_stream()
        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), 3)
            except asyncio.TimeoutError:
                pass
            self._server = None

    async def stop_stream(self):
        """End whatever stream is running."""
        task, self._current_task = self._current_task, None
        proc, self._current = self._current, None
        if proc:
            await _end_process(proc)
        if task and not task.done():
            task.cancel()

    @property
    def streaming(self) -> bool:
        return self._current is not None and self._current.returncode is None

    # ---- HTTP ---------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
                return
            request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
            parts = request_line.split(" ")
            if len(parts) != 3:
                await _respond(writer, 400, {"error": "bad request"})
                return
            method, target, _ = parts
            url = urlsplit(target)
            if method == "OPTIONS":
                await _respond(writer, 204, None)
                return
            if method != "GET":
                await _respond(writer, 405, {"error": "method not allowed"})
                return
            query = parse_qs(url.query)
            if not secrets.compare_digest((query.get("token") or [""])[0], self.token):
                await _respond(writer, 403, {"error": "bad token"})
                return
            if url.path == "/ping":
                await _respond(writer, 200, {"ok": True, "streaming": self.streaming})
            elif url.path == "/stream":
                self._current_task = asyncio.current_task()
                await self._stream(writer, query)
            else:
                await _respond(writer, 404, {"error": "not found"})
        except asyncio.CancelledError:
            pass
        except Exception:  # never let one request take the server down
            log.exception("Request failed")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _stream(self, writer: asyncio.StreamWriter, query: dict):
        try:
            codec = (query.get("codec") or ["h264"])[0]
            height = int((query.get("h") or ["720"])[0])
            fps = int((query.get("fps") or ["30"])[0])
            argv = await self.command_factory(codec, height, fps)
        except remote.RemoteError as e:
            await _respond(writer, 400, {"error": str(e)})
            return
        except ValueError:
            await _respond(writer, 400, {"error": "h and fps must be numbers"})
            return

        # One viewer at a time.
        old = self._current
        if old:
            self._current = None
            await _end_process(old)

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env_factory(),
            start_new_session=True,
        )
        self._current = proc
        errors = bytearray()
        err_task = asyncio.ensure_future(_drain(proc.stderr, errors))
        self.viewer_count += 1
        started = False
        try:
            try:
                first = await asyncio.wait_for(proc.stdout.read(CHUNK), FIRST_BYTES_TIMEOUT)
            except asyncio.TimeoutError:
                first = b""
            if not first:
                await _end_process(proc)
                await _settle(err_task)
                await _respond(writer, 502, {"error": self._failure(proc, errors, timed_out=proc.returncode is None)})
                return
            started = True
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Type: {CONTENT_TYPES.get(codec, 'application/octet-stream')}\r\n".encode()
                + b"Cache-Control: no-store\r\n"
                + _cors()
                + b"Connection: close\r\n\r\n"
            )
            chunk = first
            while chunk:
                writer.write(chunk)
                await writer.drain()
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(CHUNK), STALL_TIMEOUT)
                except asyncio.TimeoutError:
                    log.info("Headset view stalled; ending the stream")
                    break
        except (ConnectionError, asyncio.CancelledError):
            pass  # the viewer went away
        finally:
            if self._current is proc:
                self._current = None
            await _end_process(proc)
            await _settle(err_task)
            if started and errors:
                log.info("Stream ended: %s", errors.decode(errors="replace").strip()[-500:])

    @staticmethod
    def _failure(proc, errors: bytearray, timed_out: bool) -> str:
        text = errors.decode(errors="replace").strip()
        if proc.returncode == remote.NO_DEVICE_EXIT and text:
            return text.splitlines()[-1]
        if text:
            return remote.describe_ssh_failure(proc.returncode or 0, text)
        if timed_out:
            return ("The Frame sent no video for 20 s. Start SteamVR on the Frame and put the headset on "
                    "(the mirror is blank while it's asleep).")
        return f"The stream ended before any video arrived (exit status {proc.returncode})."


def _cors() -> bytes:
    return (
        b"Access-Control-Allow-Origin: *\r\n"
        b"Access-Control-Allow-Methods: GET, OPTIONS\r\n"
        b"Access-Control-Allow-Headers: *\r\n"
        b"Access-Control-Allow-Private-Network: true\r\n"
    )


async def _respond(writer: asyncio.StreamWriter, status: int, body):
    reasons = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
               405: "Method Not Allowed", 502: "Bad Gateway"}
    payload = b"" if body is None else json.dumps(body).encode()
    head = (f"HTTP/1.1 {status} {reasons.get(status, 'Error')}\r\n".encode() + _cors()
            + b"Cache-Control: no-store\r\nConnection: close\r\n")
    if payload:
        head += b"Content-Type: application/json\r\n"
    head += f"Content-Length: {len(payload)}\r\n\r\n".encode()
    try:
        writer.write(head + payload)
        await writer.drain()
    except ConnectionError:
        pass


async def _drain(stream: asyncio.StreamReader, into: bytearray):
    while True:
        data = await stream.read(4096)
        if not data:
            return
        into += data
        if len(into) > STDERR_LIMIT:
            del into[: len(into) - STDERR_LIMIT]


async def _settle(task: asyncio.Future, timeout: float = 2.0):
    try:
        await asyncio.wait_for(task, timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
        pass


async def _end_process(proc: asyncio.subprocess.Process):
    """Close ssh's stdin (the Frame then stops ffmpeg) and make sure it exits."""
    if proc.returncode is not None:
        return
    try:
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
    except Exception:
        pass
    try:
        await asyncio.wait_for(proc.wait(), 2)
        return
    except asyncio.TimeoutError:
        pass
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), 3)
    except (ProcessLookupError, asyncio.TimeoutError):
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
