import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  Navigation,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { definePlugin, routerHook, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaVrCardboard } from "react-icons/fa";
import * as api from "./backend";
import type { Result, Settings } from "./backend";
import { PlayerView } from "./PlayerView";
import { VIEWER_ROUTE, ViewerPage } from "./ViewerPage";

const RESOLUTIONS = [
  { data: 480, label: "480p (lightest)" },
  { data: 720, label: "720p" },
  { data: 1080, label: "1080p (most Wi-Fi)" },
];
const FRAME_RATES = [
  { data: 30, label: "30 fps" },
  { data: 60, label: "60 fps" },
];
const CODECS = [
  { data: "auto", label: "Automatic" },
  { data: "h264", label: "H.264 (sharper, less Wi-Fi)" },
  { data: "mjpeg", label: "MJPEG (compatibility)" },
];

function PairModal({ closeModal, onDone }: { closeModal?: () => void; onDone: (r: Result) => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <ConfirmModal
      strTitle="Pair with Steam Frame"
      strDescription={
        "Enter the password you set on the Frame under Settings > Developer > Set User Password. " +
        "It's used once to install this Deck's key on the headset and is not stored."
      }
      strOKButtonText={busy ? "Pairing…" : "Pair"}
      bOKDisabled={busy || !password}
      onCancel={closeModal}
      onOK={async () => {
        setBusy(true);
        const r = await api.pair(password).catch((e) => ({ ok: false, message: String(e) }));
        setBusy(false);
        onDone(r);
        if (r.ok) closeModal?.();
      }}
    >
      <TextField
        label="Developer Mode password"
        bIsPassword
        focusOnMount
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
    </ConfirmModal>
  );
}

function Content() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [host, setHost] = useState("");
  const [user, setUser] = useState("");
  const [status, setStatus] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s);
      setHost(s.host);
      setUser(s.user);
      if (s.paired_key) api.testConnection().then(setStatus);
    });
  }, []);

  const save = async (changes: Partial<Settings>) => {
    const r = await api.setSettings(changes);
    setSettings(r.settings);
    if (!r.ok) toaster.toast({ title: "Frame View", body: r.message ?? "Couldn't save that setting." });
    return r.ok;
  };

  const saveConnection = async () => {
    if (!settings || (host === settings.host && user === settings.user)) return true;
    const ok = await save({ host: host.trim(), user: user.trim() });
    if (ok) setStatus(null);
    return ok;
  };

  const check = async () => {
    setBusy(true);
    try {
      if (await saveConnection()) setStatus(await api.testConnection());
    } finally {
      setBusy(false);
    }
  };

  const startPairing = async () => {
    if (!(await saveConnection())) return;
    showModal(
      <PairModal
        onDone={(r) => {
          setStatus(r);
          toaster.toast({ title: r.ok ? "Paired with Steam Frame" : "Pairing failed", body: r.message });
          api.getSettings().then(setSettings);
        }}
      />,
    );
  };

  if (!settings) return <PanelSection>Loading…</PanelSection>;

  const ready = settings.paired_key && status?.ok;

  return (
    <>
      <PanelSection title="Headset view">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!settings.paired_key}
            onClick={() => {
              Navigation.Navigate(VIEWER_ROUTE);
              Navigation.CloseSideMenus();
            }}
          >
            Open full screen
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Preview here"
            checked={preview}
            disabled={!settings.paired_key}
            onChange={setPreview}
          />
        </PanelSectionRow>
        {preview && (
          <PanelSectionRow>
            <PlayerView generation={0} compact style={{ width: "100%", aspectRatio: "16 / 9", borderRadius: 4 }} />
          </PanelSectionRow>
        )}
        {status && (
          <PanelSectionRow>
            <Field
              focusable
              description={status.message}
              label={ready ? "Connected" : settings.paired_key ? "Not connected" : "Not paired"}
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Connection">
        <PanelSectionRow>
          <TextField
            label="Frame hostname or IP"
            description="Shown on the Frame in Quick Settings or Settings > Internet"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            onBlur={saveConnection}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField label="User" value={user} onChange={(e) => setUser(e.target.value)} onBlur={saveConnection} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={startPairing}>
            {settings.paired_key ? "Pair again" : "Pair with Frame"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || !settings.paired_key} onClick={check}>
            {busy ? "Checking…" : "Test connection"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Quality">
        <PanelSectionRow>
          <DropdownItem
            label="Resolution"
            rgOptions={RESOLUTIONS}
            selectedOption={settings.height}
            onChange={(o) => save({ height: o.data })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Frame rate"
            rgOptions={FRAME_RATES}
            selectedOption={settings.fps}
            onChange={(o) => save({ fps: o.data })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Video format"
            rgOptions={CODECS}
            selectedOption={settings.codec}
            onChange={(o) => save({ codec: o.data })}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Troubleshooting">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              const r = await api.forgetHostKey();
              setStatus(null);
              toaster.toast({ title: "Frame View", body: r.message });
            }}
          >
            Forget headset key
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(VIEWER_ROUTE, ViewerPage, { exact: true });

  return {
    name: "Frame View",
    titleView: <div className={staticClasses.Title}>Frame View</div>,
    content: <Content />,
    icon: <FaVrCardboard />,
    onDismount() {
      routerHook.removeRoute(VIEWER_ROUTE);
      api.stopStream().catch(() => {});
    },
  };
});
