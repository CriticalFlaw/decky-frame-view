"""Commands run on the Steam Frame, and the ssh commands that run them.

How the headset view is captured (the same route Frame Control takes):
SteamVR's ``steamvr-v4l2cam.service`` copies the headset mirror (one
undistorted 1920x1080 eye, fully composited: passthrough, panels, the game)
into the v4l2loopback device ``/dev/video99``. SteamOS on the Frame ships
``ffmpeg``, so the Frame encodes that device and the raw stream comes back
over SSH. The Frame's hardware encoder crashes ffmpeg, so H.264 uses libx264
``ultrafast``/``zerolatency``.

``ffmpeg`` runs in the background while the remote shell waits for our stdin
to close. When the local ssh goes away the channel closes, ``cat`` returns and
the shell kills ffmpeg, even one that has stopped writing (and so would never
see SIGPIPE).
"""

from __future__ import annotations

import os
import re
import shlex

DEVICE = "/dev/video99"

HEIGHTS = (480, 720, 1080)
FPS = (30, 60)
CODECS = ("h264", "mjpeg")

# Mbit/s for H.264 at each height.
H264_RATE = {480: 2, 720: 3, 1080: 6}
# ffmpeg -q:v for MJPEG (2 best .. 31 worst). Higher resolutions get a little
# more compression so Wi-Fi keeps up.
MJPEG_QUALITY = {480: 5, 720: 7, 1080: 9}

HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.%A-Za-z]+\]|[0-9A-Fa-f:.]+)$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

NO_DEVICE_EXIT = 3


class RemoteError(Exception):
    """A problem worth showing to the user as is."""


def check_host(host: str) -> str:
    host = (host or "").strip()
    if not host or host.startswith("-") or not HOST_RE.match(host):
        raise RemoteError("Enter the Frame's hostname (e.g. frame.local) or IP address.")
    return host


def check_user(user: str) -> str:
    user = (user or "").strip()
    if not USER_RE.match(user):
        raise RemoteError("The SSH user should be a plain Linux user name (the Frame's is 'steamos').")
    return user


def check_port(port) -> int:
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise RemoteError("The SSH port must be a number.")
    if not 1 <= port <= 65535:
        raise RemoteError("The SSH port must be between 1 and 65535.")
    return port


def stream_command(codec: str, height: int, fps: int) -> str:
    """The shell command that streams the headset view from the Frame to stdout."""
    if codec not in CODECS:
        raise RemoteError(f"Unknown codec {codec!r}")
    if height not in HEIGHTS:
        raise RemoteError(f"Height must be one of {HEIGHTS}")
    if fps not in FPS:
        raise RemoteError(f"Frame rate must be one of {FPS}")

    scale = f"fps={fps},scale=-2:{height}"
    if codec == "h264":
        rate = H264_RATE[height]
        encode = (
            f"-vf {scale},format=yuv420p -c:v libx264 -preset ultrafast -tune zerolatency "
            f"-g {fps * 2} -bf 0 -b:v {rate}M -maxrate {rate}M -bufsize {max(rate // 2, 1)}M "
            # An access unit delimiter before every frame lets the viewer split
            # the stream; repeated SPS/PPS let it start at any keyframe.
            f"-x264-params aud=1:repeat-headers=1 -f h264 -"
        )
    else:
        encode = f"-vf {scale},format=yuvj420p -c:v mjpeg -q:v {MJPEG_QUALITY[height]} -f mjpeg -"

    return (
        f"[ -e {DEVICE} ] || {{ echo 'The headset view device ({DEVICE}) is missing. Is SteamVR running on the Frame?' >&2; exit {NO_DEVICE_EXIT}; }}; "
        f"command -v ffmpeg >/dev/null || {{ echo 'ffmpeg was not found on the Frame.' >&2; exit 4; }}; "
        f"ffmpeg -hide_banner -loglevel error -nostdin -f v4l2 -video_size 1920x1080 -i {DEVICE} {encode} & p=$!; "
        f"exec >&-; cat >/dev/null; kill $p 2>/dev/null; wait $p"
    )


# Prints one line per check; parsed by parse_probe.
PROBE_COMMAND = (
    f"[ -e {DEVICE} ] && echo device=yes || echo device=no; "
    "command -v ffmpeg >/dev/null && echo ffmpeg=yes || echo ffmpeg=no; "
    # [v] keeps pgrep -f from matching this very command line.
    "pgrep -f '[v]rcompositor' >/dev/null 2>&1 && echo steamvr=yes || echo steamvr=no; "
    "echo host=$(hostname)"
)


def parse_probe(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return {
        "device": out.get("device") == "yes",
        "ffmpeg": out.get("ffmpeg") == "yes",
        "steamvr": out.get("steamvr") == "yes",
        "hostname": out.get("host", ""),
    }


# Installs the public key (read from stdin) into authorized_keys once.
INSTALL_KEY_COMMAND = (
    "umask 077; mkdir -p ~/.ssh && k=$(cat) && "
    "{ grep -qxF \"$k\" ~/.ssh/authorized_keys 2>/dev/null || printf '%s\\n' \"$k\" >> ~/.ssh/authorized_keys; } && "
    "echo paired"
)


class SSH:
    """Builds ssh invocations for one headset with this plugin's own key."""

    def __init__(self, key_path: str, known_hosts: str, ssh_binary: str = "ssh"):
        self.key_path = key_path
        self.known_hosts = known_hosts
        self.ssh_binary = ssh_binary

    def base(self, host: str, user: str, port: int, *, batch: bool = True, connect_timeout: int = 8) -> list[str]:
        args = [
            self.ssh_binary,
            "-T",
            "-p", str(check_port(port)),
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            # The first connection pins the Frame's host key; a changed key is refused.
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={connect_timeout}",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR",
            "-F", "/dev/null",
        ]
        if batch:
            args += ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", self.key_path]
        else:
            args += [
                "-o", "BatchMode=no",
                "-o", "PubkeyAuthentication=no",
                "-o", "PreferredAuthentications=password,keyboard-interactive",
                "-o", "NumberOfPasswordPrompts=1",
            ]
        args.append(f"{check_user(user)}@{check_host(host)}")
        return args

    def command(self, host: str, user: str, port: int, remote: str, **kw) -> list[str]:
        return [*self.base(host, user, port, **kw), remote]


def clean_env(home: str | None = None) -> dict:
    """The environment for ssh and ssh-keygen.

    Decky Loader is a PyInstaller bundle and plugin processes inherit its
    LD_LIBRARY_PATH, which can make system binaries load the wrong libcrypto.
    """
    env = dict(os.environ)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    env.pop("LD_LIBRARY_PATH", None)
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    env.pop("SSH_AUTH_SOCK", None)
    if home:
        env["HOME"] = home
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin")
    return env


def describe_ssh_failure(returncode: int, stderr: str) -> str:
    """Turn ssh's stderr into something a person can act on."""
    err = (stderr or "").strip()
    low = err.lower()
    if "permission denied" in low:
        return "The Frame refused this Deck's key. Pair again with the Frame's Developer Mode password."
    if "host key verification failed" in low or "remote host identification has changed" in low:
        return ("The Frame's identity changed since pairing (reinstalled or a different device). "
                "Use 'Forget headset key' and pair again.")
    if "could not resolve hostname" in low or "name or service not known" in low:
        return "Couldn't find the Frame on the network. Check the hostname, or use its IP address (Quick Settings on the Frame)."
    if "connection refused" in low:
        return "The Frame refused the connection. Turn on Developer Mode on the Frame (Settings > System), which enables SSH."
    if "timed out" in low or "no route to host" in low or "network is unreachable" in low:
        return "The Frame didn't answer. Make sure it's on, awake and on the same network as the Deck."
    if err:
        return err.splitlines()[-1][:300]
    return f"ssh exited with status {returncode}"


def quote(s: str) -> str:
    return shlex.quote(s)
