import { ButtonItem, PanelSection, PanelSectionRow, Field, staticClasses, TextField } from "@decky/ui";
import { callable, definePlugin } from "@decky/api"
import { useState } from "react";
import { FaVrCardboard } from "react-icons/fa";

const testConnection = callable<[host: string], string>("test_connection");

function Content() {
  const [host, setHost] = useState("frame.local");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);

  const test = async () => {
    setBusy(true);
    setResult("");
    try {
      setResult(await testConnection(host));
    } catch (e) {
      setResult(`Error: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Connection">
      <PanelSectionRow>
        <TextField label="Steam Frame hostname or IP" value={host} onChange={(e) => setHost(e.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={test}>
          {busy ? "Testing…" : "Test connection"}
        </ButtonItem>
      </PanelSectionRow>
      {result && (
        <PanelSectionRow>
          <Field focusable description={result} />
          </PanelSectionRow>
        )}
    </PanelSection>
  );
};

export default definePlugin(() => {
  console.log("Frame View plugin initializing...")

  return {
    // The name shown in various decky menus
    name: "Frame View",
    // The element displayed at the top of your plugin's menu
    titleView: <div className={staticClasses.Title}>Frame View</div>,
    // The content of your plugin's menu
    content: <Content />,
    // The icon displayed in the plugin list
    icon: <FaVrCardboard />,
    // The function triggered when your plugin unloads
    onDismount() {
      console.log("Unloading")
    },
  };
});
