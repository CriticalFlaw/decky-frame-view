import { useEffect, useRef, useState, CSSProperties } from "react";
import { streamInfo } from "./backend";
import { PlayerStatus, StreamPlayer } from "./player";

interface Props {
  /** Bumping this restarts the stream. */
  generation: number;
  style?: CSSProperties;
  compact?: boolean;
  onStatus?: (s: PlayerStatus) => void;
}

/** A canvas showing the Frame's headset view, with a small status overlay. */
export function PlayerView({ generation, style, compact, onStatus }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState<PlayerStatus>({ state: "connecting" });

  useEffect(() => {
    let player: StreamPlayer | null = null;
    let cancelled = false;
    const update = (s: PlayerStatus) => {
      if (cancelled) return;
      setStatus(s);
      onStatus?.(s);
    };
    update({ state: "connecting" });
    (async () => {
      try {
        const info = await streamInfo();
        if (cancelled || !canvas.current) return;
        player = new StreamPlayer({ ...info, canvas: canvas.current, onStatus: update });
        await player.start();
      } catch (e: any) {
        update({ state: "error", message: e?.message || String(e) });
      }
    })();
    return () => {
      cancelled = true;
      // Aborting the fetch closes the connection, which ends the stream on the
      // backend (and ffmpeg on the Frame). Not calling stop_stream here keeps a
      // viewer that has just opened elsewhere running.
      player?.stop();
    };
  }, [generation]);

  const playing = status.state === "playing";
  const font = compact ? "11px" : "14px";

  return (
    <div style={{ position: "relative", background: "#000", overflow: "hidden", ...style }}>
      <canvas
        ref={canvas}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "contain",
          display: "block",
          visibility: playing ? "visible" : "hidden",
        }}
      />
      {!playing && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            padding: compact ? "8px" : "24px",
            fontSize: compact ? "12px" : "16px",
            color: status.state === "error" ? "#ff8a80" : "#dcdedf",
          }}
        >
          {status.state === "error"
            ? status.message
            : status.state === "stopped"
              ? "Stopped"
              : "Connecting to the Frame…"}
        </div>
      )}
      {playing && (
        <div
          style={{
            position: "absolute",
            right: compact ? 4 : 10,
            bottom: compact ? 4 : 10,
            padding: "2px 6px",
            borderRadius: 4,
            background: "rgba(0,0,0,0.55)",
            color: "#dcdedf",
            fontSize: font,
            pointerEvents: "none",
          }}
        >
          {status.height}p · {status.fps ?? 0} fps · {status.codec === "h264" ? "H.264" : "MJPEG"}
        </div>
      )}
    </div>
  );
}
