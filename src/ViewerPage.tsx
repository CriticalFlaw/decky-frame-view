import { Focusable, Navigation } from "@decky/ui";
import { useState } from "react";
import { PlayerView } from "./PlayerView";
import type { PlayerStatus } from "./player";

export const VIEWER_ROUTE = "/frame-view";

/** Full-screen headset view. A restarts the stream, B goes back. */
export function ViewerPage() {
  const [generation, setGeneration] = useState(0);
  const [status, setStatus] = useState<PlayerStatus>({ state: "connecting" });

  return (
    <Focusable
      style={{
        position: "absolute",
        inset: 0,
        paddingTop: "40px", // below Steam's top bar
        background: "#000",
        display: "flex",
        flexDirection: "column",
      }}
      noFocusRing
      onActivate={() => setGeneration((g) => g + 1)}
      onOKActionDescription={status.state === "playing" ? "Reconnect" : "Retry"}
      onCancel={() => Navigation.NavigateBack()}
      onCancelActionDescription="Back"
    >
      <PlayerView generation={generation} onStatus={setStatus} style={{ flex: 1, width: "100%" }} />
    </Focusable>
  );
}
