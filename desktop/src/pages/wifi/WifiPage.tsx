/**
 * Drone Wi-Fi — which network the drone's camera is on, and changing it.
 *
 * Laid out like Control (2026-09-24: "follow the UI design language of the
 * control page"): the console on the left — the link, and the camera itself,
 * so "is it working" is answered by looking — and the setting on the right.
 * The picker only opens on Change; with a network saved the right column is
 * one small card.
 *
 * THREE DIFFERENT "CONNECTED"s, kept apart, because running them together is
 * what made a failed join look like success:
 *
 *   Radio    the laptop talks to the drone over the Crazyradio
 *   Network  the drone's AI deck joined a Wi-Fi network and has an address
 *   Camera   this laptop can reach that address and frames arrive
 */

import { useEffect, useState } from "react";
import { api, type CameraStatus, type CameraWifi, type Session } from "@/lib/agent";
import { PHASE_LABEL, PHASE_TONE, droneWifi } from "@/lib/droneWifi";
import { useMediaQuery, WIDE } from "@/lib/useMediaQuery";
import { DroneWifiForm } from "@/components/DroneWifiForm";
import { CameraPane } from "@/pages/control/CameraPane";
import { Button, PageHeader, Panel, StatusDot, TONE_COLOR, TONE_ICON, type Tone } from "@/components/ui";

/** How often the camera's reachability is re-read while this page is open. */
const CAMERA_POLL_MS = 3000;

export function WifiPage({ wifi, session, onSaved }: {
  wifi: CameraWifi | null;
  session: Session | null;
  onSaved: (state: CameraWifi) => void;
}) {
  const wide = useMediaQuery(WIDE);
  const [camera, setCamera] = useState<CameraStatus | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stopped = false;
    const read = () => api.cameraStatus()
      .then((s) => { if (!stopped) setCamera(s); })
      .catch(() => { if (!stopped) setCamera(null); });
    void read();
    const timer = window.setInterval(read, CAMERA_POLL_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    droneWifi.saved().then(setSaved).catch(() => setSaved(null));
  }, [wifi?.ssid]);

  const radio = session?.radio;
  const phase = wifi?.phase ?? "not-set";
  const showForm = editing || !saved;

  const forget = async () => {
    setBusy(true);
    try {
      await droneWifi.forget();
      setSaved(null);
      onSaved({ ssid: null, phase: "not-set", ip: null, message: null });
    } finally {
      setBusy(false);
    }
  };

  const link = (
    <section aria-label="Link" className="flex min-h-0 flex-1 flex-col border border-[var(--console-line)] bg-[var(--console)]">
      <h2 className="mono shrink-0 border-b border-[var(--console-line)] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--console-dim)]">
        Link
      </h2>
      <dl className="grid shrink-0 border-b border-[var(--console-line)] px-3 py-2">
        <Line
          tone={radio?.state === "connected" ? "good" : radio?.state === "searching" ? "warning" : "idle"}
          label="Radio"
          value={radio?.state === "connected" ? radio.hardware_id ?? "Connected" : radio?.message ?? "Not connected"}
        />
        <Line
          tone={PHASE_TONE[phase]}
          label="Network"
          value={phase === "joined" && wifi?.ip
            ? [wifi.ssid, wifi.ip, wifi.rssi != null ? `${wifi.rssi} dBm` : null].filter(Boolean).join(" · ")
            : wifi?.message && (phase === "reconnecting" || phase === "failed") ? wifi.message : PHASE_LABEL[phase]}
        />
        <Line
          tone={camera?.live ? "good" : "idle"}
          label="Camera"
          value={camera?.live
            ? `Streaming${camera.width && camera.height ? ` · ${camera.width}×${camera.height}` : ""}`
            : "No frames"}
        />
      </dl>
      <CameraPane active />
    </section>
  );

  const setting = (
    <Panel
      title="Network"
      action={saved && !showForm ? (
        <div className="flex gap-2">
          <Button onClick={() => setEditing(true)}>Change</Button>
          <Button onClick={() => void forget()} disabled={busy}>Forget</Button>
        </div>
      ) : undefined}
    >
      {showForm ? (
        <DroneWifiForm
          onSaved={(state) => { setSaved(state.ssid); setEditing(false); onSaved(state); }}
          onCancel={saved ? () => setEditing(false) : undefined}
        />
      ) : (
        <div className="grid gap-2 text-sm">
          <p className="wrap-anywhere text-base font-semibold">{saved}</p>
          <StatusDot tone={PHASE_TONE[phase]}>{wifi?.message ?? PHASE_LABEL[phase]}</StatusDot>
        </div>
      )}
      {editing && phase === "joined" && (
        <p className="mt-3 text-xs text-[var(--muted)]">
          The drone keeps its current network until it restarts.
        </p>
      )}
    </Panel>
  );

  return (
    <div className="grid gap-4">
      <PageHeader eyebrow="Operate" title="Drone Wi-Fi" />
      {wide ? (
        <div className="grid h-[calc(100vh-9.5rem)] min-h-[28rem] grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-3">
          <div className="flex min-h-0 flex-col">{link}</div>
          <div className="min-h-0 overflow-y-auto">{setting}</div>
        </div>
      ) : (
        <div className="grid gap-3">
          {setting}
          <div className="flex h-[32rem] flex-col">{link}</div>
        </div>
      )}
    </div>
  );
}

/** One status row, in the console's own grammar: glyph, label, value. */
function Line({ tone, label, value }: { tone: Tone; label: string; value: string }) {
  return (
    <div className="grid grid-cols-[1.25rem_5rem_minmax(0,1fr)] items-baseline gap-x-2 py-1 text-xs">
      <span aria-hidden="true" style={{ color: TONE_COLOR[tone] }}>{TONE_ICON[tone]}</span>
      <dt className="mono text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">{label}</dt>
      <dd className="wrap-anywhere text-[var(--console-ink)]">{value}</dd>
    </div>
  );
}
