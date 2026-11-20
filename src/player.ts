// Plays the headset view streamed by the plugin backend onto a <canvas>.
//
// H.264: raw Annex B with an access unit delimiter (NAL type 9) before every
// frame, decoded with WebCodecs. MJPEG: concatenated JPEGs, decoded with
// createImageBitmap. Both arrive over a plain fetch() from the backend's
// loopback server. No Decky imports here, so this file also runs in tests.

export type Codec = "h264" | "mjpeg";
export type CodecChoice = Codec | "auto";

export interface PlayerStatus {
  state: "connecting" | "playing" | "error" | "stopped";
  codec?: Codec;
  fps?: number;
  width?: number;
  height?: number;
  message?: string;
}

export interface PlayerOptions {
  base: string; // http://127.0.0.1:<port>
  token: string;
  codec: CodecChoice;
  height: number;
  fps: number;
  canvas: HTMLCanvasElement;
  onStatus: (s: PlayerStatus) => void;
}

class UnsupportedCodec extends Error {}

const MAX_BUFFER = 8 << 20;

export function h264Supported(): boolean {
  return typeof (globalThis as any).VideoDecoder === "function" && typeof (globalThis as any).EncodedVideoChunk === "function";
}

function startCode(b: Uint8Array, i: number) {
  return b[i] === 0 && b[i + 1] === 0 && b[i + 2] === 1;
}

/** NAL unit types in one access unit, and the offset of the SPS payload if present. */
export function scanNals(au: Uint8Array): { types: number[]; sps: number } {
  const types: number[] = [];
  let sps = -1;
  for (let i = 0; i + 3 < au.length; i++) {
    if (!startCode(au, i)) continue;
    const t = au[i + 3] & 0x1f;
    types.push(t);
    if (t === 7 && sps < 0) sps = i + 4;
    i += 3;
  }
  return { types, sps };
}

/** Splits an Annex B byte stream into access units at each AUD. */
export class AccessUnitSplitter {
  private buf = new Uint8Array(0);
  private scan = 0;
  private start = -1;

  push(chunk: Uint8Array, onUnit: (au: Uint8Array) => void) {
    const next = new Uint8Array(this.buf.length + chunk.length);
    next.set(this.buf);
    next.set(chunk, this.buf.length);
    this.buf = next;
    if (this.buf.length > MAX_BUFFER) throw new Error("The video stream isn't split into frames.");
    for (; this.scan + 3 < this.buf.length; this.scan++) {
      if (!startCode(this.buf, this.scan) || (this.buf[this.scan + 3] & 0x1f) !== 9) continue;
      if (this.start >= 0) onUnit(this.buf.slice(this.start, this.scan));
      this.start = this.scan;
      this.scan += 3;
    }
    if (this.start > 0) {
      this.buf = this.buf.slice(this.start);
      this.scan -= this.start;
      this.start = 0;
    }
  }
}

/** Splits concatenated JPEGs (SOI ... EOI). */
export class JpegSplitter {
  private buf = new Uint8Array(0);
  private scan = 0;

  push(chunk: Uint8Array, onImage: (jpeg: Uint8Array) => void) {
    const next = new Uint8Array(this.buf.length + chunk.length);
    next.set(this.buf);
    next.set(chunk, this.buf.length);
    this.buf = next;
    if (this.buf.length > MAX_BUFFER) throw new Error("The MJPEG stream has no image boundaries.");
    let start = 0;
    // Entropy-coded JPEG data stuffs every 0xFF with 0x00, so FF D9 only appears as the EOI marker.
    for (let i = Math.max(this.scan, 1); i < this.buf.length; i++) {
      if (this.buf[i - 1] === 0xff && this.buf[i] === 0xd9) {
        const s = this.findSoi(start);
        if (s >= 0 && s < i) onImage(this.buf.slice(s, i + 1));
        start = i + 1;
      }
    }
    this.buf = this.buf.slice(start);
    this.scan = this.buf.length;
  }

  private findSoi(from: number) {
    for (let i = from; i + 1 < this.buf.length; i++) if (this.buf[i] === 0xff && this.buf[i + 1] === 0xd8) return i;
    return -1;
  }
}

export class StreamPlayer {
  private ctl: AbortController | null = null;
  private stopped = false;
  private decoder: any = null;
  private frames = 0;
  private second = 0;
  private lastStatus: PlayerStatus = { state: "stopped" };

  constructor(private opts: PlayerOptions) {}

  get status() {
    return this.lastStatus;
  }

  async start() {
    this.stopped = false;
    const choice = this.opts.codec;
    const first: Codec = choice === "mjpeg" || (choice === "auto" && !h264Supported()) ? "mjpeg" : "h264";
    try {
      await this.run(first);
    } catch (e: any) {
      if (this.stopped || e?.name === "AbortError") return;
      if (choice === "auto" && first === "h264" && e instanceof UnsupportedCodec) {
        // Steam's browser can't decode H.264 here: fall back to MJPEG.
        try {
          await this.run("mjpeg");
          return;
        } catch (e2: any) {
          if (this.stopped || e2?.name === "AbortError") return;
          e = e2;
        }
      }
      this.emit({ state: "error", message: e?.message || String(e) });
    }
  }

  stop() {
    this.stopped = true;
    this.ctl?.abort();
    this.ctl = null;
    this.closeDecoder();
    this.emit({ state: "stopped" });
  }

  private emit(s: PlayerStatus) {
    this.lastStatus = s;
    this.opts.onStatus(s);
  }

  private closeDecoder() {
    try {
      if (this.decoder && this.decoder.state !== "closed") this.decoder.close();
    } catch {
      /* already closed */
    }
    this.decoder = null;
  }

  private tick(codec: Codec, w: number, h: number) {
    this.frames++;
    const now = performance.now();
    if (this.frames === 1 && this.lastStatus.state !== "playing") {
      this.second = now;
      this.emit({ state: "playing", codec, width: w, height: h, fps: 0 });
      return;
    }
    if (now - this.second >= 1000) {
      const fps = Math.round(((this.frames - 1) * 1000) / (now - this.second));
      this.frames = 1;
      this.second = now;
      this.emit({ state: "playing", codec, width: w, height: h, fps });
    }
  }

  private draw(src: CanvasImageSource, w: number, h: number) {
    const c = this.opts.canvas;
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    c.getContext("2d")!.drawImage(src, 0, 0, w, h);
  }

  private async open(codec: Codec): Promise<ReadableStreamDefaultReader<Uint8Array>> {
    this.ctl?.abort();
    const ctl = (this.ctl = new AbortController());
    const { base, token, height, fps } = this.opts;
    this.frames = 0;
    this.emit({ state: "connecting", codec });
    const url = `${base}/stream?token=${encodeURIComponent(token)}&codec=${codec}&h=${height}&fps=${fps}`;
    let r: Response;
    try {
      r = await fetch(url, { signal: ctl.signal, cache: "no-store" });
    } catch (e: any) {
      if (e?.name === "AbortError") throw e;
      throw new Error("Couldn't reach the Frame View backend. Try reloading Decky.");
    }
    if (!r.ok) {
      const body = await r.json().catch(() => ({}) as any);
      throw new Error(body.error || `The backend answered HTTP ${r.status}.`);
    }
    if (!r.body) throw new Error("This browser can't stream fetch responses.");
    return r.body.getReader();
  }

  private async run(codec: Codec) {
    if (codec === "h264") return this.runH264();
    return this.runMjpeg();
  }

  private async runH264() {
    const VD = (globalThis as any).VideoDecoder;
    const EVC = (globalThis as any).EncodedVideoChunk;
    if (!VD || !EVC) throw new UnsupportedCodec("WebCodecs isn't available.");
    const reader = await this.open("h264");
    const fps = this.opts.fps;
    let needKey = true;
    let ts = 0;
    let fatal: Error | null = null;
    let configuring: Promise<void> | null = null;
    const pending: Uint8Array[] = [];

    const decoder = (this.decoder = new VD({
      output: (frame: any) => {
        if (this.stopped) return frame.close();
        this.draw(frame, frame.displayWidth, frame.displayHeight);
        const w = frame.displayWidth, h = frame.displayHeight;
        frame.close();
        this.tick("h264", w, h);
      },
      error: (e: any) => {
        fatal = new UnsupportedCodec(`H.264 decoding failed: ${e?.message || e}`);
      },
    }));

    const feed = (au: Uint8Array) => {
      const { types } = scanNals(au);
      const key = types.includes(5);
      if (decoder.state !== "configured") return;
      // If decoding falls behind, drop frames until the next keyframe rather than lag.
      if (decoder.decodeQueueSize > 3) needKey = true;
      if (needKey && !key) return;
      needKey = false;
      decoder.decode(new EVC({ type: key ? "key" : "delta", timestamp: ts, data: au }));
      ts += 1e6 / fps;
    };

    const onUnit = (au: Uint8Array) => {
      if (decoder.state === "unconfigured" && !configuring) {
        const { sps } = scanNals(au);
        if (sps < 0 || sps + 3 > au.length) return;
        const hex = [au[sps], au[sps + 1], au[sps + 2]].map((b) => b.toString(16).padStart(2, "0")).join("");
        const config = { codec: `avc1.${hex}`, optimizeForLatency: true };
        pending.push(au);
        configuring = Promise.resolve(VD.isConfigSupported ? VD.isConfigSupported(config) : { supported: true }).then(
          (res: any) => {
            if (!res?.supported) throw new UnsupportedCodec(`This Steam browser can't decode ${config.codec}.`);
            decoder.configure(config);
            pending.splice(0).forEach(feed);
          },
        );
        return;
      }
      if (decoder.state === "unconfigured") {
        pending.push(au);
        if (pending.length > 120) pending.shift();
        return;
      }
      feed(au);
    };

    const split = new AccessUnitSplitter();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (this.stopped) return;
        if (done) break;
        split.push(value, onUnit);
        if (configuring) await configuring;
        if (fatal) throw fatal;
      }
    } finally {
      reader.cancel().catch(() => {});
    }
    if (!this.stopped) throw new Error(this.frames ? "The headset view stopped (the Frame went to sleep or SteamVR closed)." : "No video arrived.");
  }

  private async runMjpeg() {
    const reader = await this.open("mjpeg");
    const split = new JpegSplitter();
    let latest: Uint8Array | null = null;
    let busy = false;

    const show = async () => {
      if (busy) return;
      busy = true;
      try {
        while (latest && !this.stopped) {
          const jpeg: Uint8Array = latest;
          latest = null;
          const bmp = await createImageBitmap(new Blob([jpeg as BlobPart], { type: "image/jpeg" }));
          if (this.stopped) {
            bmp.close();
            break;
          }
          this.draw(bmp, bmp.width, bmp.height);
          this.tick("mjpeg", bmp.width, bmp.height);
          bmp.close();
        }
      } catch {
        /* a damaged frame; the next one replaces it */
      } finally {
        busy = false;
      }
    };

    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (this.stopped) return;
        if (done) break;
        split.push(value, (jpeg) => {
          latest = jpeg; // only the newest frame is decoded, so a slow decode never lags
          show();
        });
      }
    } finally {
      reader.cancel().catch(() => {});
    }
    if (!this.stopped) throw new Error(this.frames ? "The headset view stopped (the Frame went to sleep or SteamVR closed)." : "No video arrived.");
  }
}
