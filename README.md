# Frame View

A [Decky Loader](https://decky.xyz) plugin that shows what a **Steam Frame** wearer sees, live on your **Steam Deck**.

It shows the same picture as the headset view in [Frame Control](https://github.com/saphid/frame-control): SteamVR's headset mirror, one undistorted eye with everything composited in (the game, SteamVR panels and dashboard, controllers and room passthrough). It's handy for watching someone play, helping a first-timer find their way through menus, or keeping an eye on kids in VR.

> Unofficial. Not made by or affiliated with Valve. It uses the Frame's Developer Mode SSH access and an undocumented SteamVR device, so a Frame update could break it.

## How it works

```
Steam Frame                                  Steam Deck
SteamVR mirror → /dev/video99                Decky plugin backend (Python)
      ↓                                            ↓
ffmpeg (on the Frame) → H.264 / MJPEG → SSH → loopback HTTP 127.0.0.1 → Steam UI (WebCodecs) → screen
```

- SteamVR on the Frame copies the headset mirror into a v4l2 loopback device, `/dev/video99`.
- The plugin connects to the Frame over SSH with its own key and runs the Frame's built-in `ffmpeg` to encode that device: H.264 (x264, ultrafast and zero latency) or MJPEG.
- The plugin backend relays the stream on a loopback-only port that needs a random token. The plugin UI in Steam decodes it with WebCodecs, or `createImageBitmap` for MJPEG, and draws it on a canvas.
- Closing the viewer closes the SSH channel, and the Frame stops `ffmpeg` straight away.

Nothing is installed on the Frame. The one change there is a line added to `~steamos/.ssh/authorized_keys` when you pair.

## Requirements

- A Steam Deck (or another SteamOS PC) with [Decky Loader](https://decky.xyz) installed.
- A Steam Frame on the same network, with **Developer Mode** on: Settings → System → Enable Developer Mode. This also turns on SSH.
- A Developer Mode password set on the Frame: Settings → Developer → Set User Password. You need it once, to pair.
- SteamVR running on the Frame, which is normal when someone is using it. While the headset is asleep or not being worn, the mirror is blank.

## Install

1. Download `decky-frame-view-<version>.zip` from [Releases](../../releases), or from the latest **Build** workflow run's artifacts.
2. On the Deck: Decky (Quick Access ⋯) → ⚙ Settings → General → turn on **Developer mode**.
3. Decky Settings → Developer → **Install Plugin from ZIP** → pick the ZIP.

## Use

1. Open Quick Access → **Frame View**.
2. Under **Connection**, set the Frame's hostname or IP. The default `frame.local` usually works. If it doesn't, use the IP shown on the Frame in Quick Settings.
3. Select **Pair with Frame** and enter the Frame's Developer Mode password. The plugin makes its own SSH key and installs it on the Frame. The password is not stored.
4. Select **Open full screen** to watch, or turn on **Preview here** for a small view in the side panel.
   - Ⓐ reconnects, Ⓑ goes back.
   - The corner shows the resolution, the actual frame rate and the video format.

### Quality

| Setting | Options | Notes |
|---|---|---|
| Resolution | 480p, 720p (default), 1080p | 720p H.264 is about 3 Mbit/s. 1080p is 6 Mbit/s and costs the Frame about 1.7 CPU cores at 60 fps. |
| Frame rate | 30 (default), 60 | |
| Video format | Automatic (default), H.264, MJPEG | Automatic uses H.264 and switches to MJPEG if Steam's browser can't decode H.264. MJPEG needs roughly 5–10× more Wi-Fi. |

## Troubleshooting

| Message | What to do |
|---|---|
| *Couldn't find the Frame on the network* | Use the Frame's IP address instead of `frame.local`. |
| *The Frame refused the connection* | Turn on Developer Mode on the Frame, which enables SSH. |
| *The Frame refused this Deck's key* | Pair again. Re-imaging or factory-resetting the Frame removes the key. |
| *The Frame's identity changed* | The Frame was reinstalled, or the IP now points at a different device. Use **Forget headset key**, then pair again. |
| *The headset view device is missing* | Start SteamVR on the Frame. |
| *The Frame sent no video for 20 s* / black picture | The headset is asleep. Put it on, or wake it. |
| Choppy picture | Lower the resolution, or set the format to H.264. 5 GHz Wi-Fi, or the Frame on Ethernet/USB networking, helps. |

Logs: the plugin's folder under `~/homebrew/logs/` on the Deck.

### Known limits

- Video only: there's no audio yet. The headset's audio could be added later from the Frame's PulseAudio monitor, as Frame Control's recorder does.
- One viewer at a time. Opening the viewer somewhere else ends the old one.
- The Deck doesn't know it's "watching a video", so it may dim or sleep after your idle timeout. Raise the timeout under Settings → Display if you'll watch hands-free for long.
- Only tested against a stand-in SSH server with a test-pattern `ffmpeg`, not yet on a real Frame + Deck. See [Development](#development).

## Development

```bash
pnpm install
pnpm run build          # frontend → dist/index.js
pnpm run typecheck
./scripts/package.sh    # → out/decky-frame-view-<version>.zip
```

Layout:

- `main.py`: the Decky entry point, with the callables the UI uses.
- `py_modules/frameview/`: the backend. `remote.py` has the ssh and `ffmpeg` commands, `server.py` the loopback stream relay, `core.py` the settings, key, pairing and connection check.
- `src/player.ts`: the stream splitters and the WebCodecs/MJPEG player. It has no Decky imports.
- `src/index.tsx`, `src/ViewerPage.tsx`, `src/PlayerView.tsx`: the Quick Access panel and the full-screen route.

### Tests

```bash
python3 -m unittest discover -s tests -v
```

The end-to-end test pairs with a real SSH server, probes it, and pulls H.264 and MJPEG streams through the relay. Point it at a Frame, or at any Linux box with `ffmpeg` and a stand-in for `/dev/video99`:

```bash
FRAMEVIEW_TEST_HOST=frame.local FRAMEVIEW_TEST_PASSWORD='…' python3 -m unittest discover -s tests -v
```

Optional variables: `FRAMEVIEW_TEST_PORT` (default 22) and `FRAMEVIEW_TEST_USER` (default `steamos`).

## Credits

The capture method (SteamVR's `/dev/video99` mirror, encoded with the Frame's `ffmpeg` over SSH) and the stream settings follow [saphid/frame-control](https://github.com/saphid/frame-control) (MIT) and its notes in `docs/how-the-frame-works.md`. Built from the [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
