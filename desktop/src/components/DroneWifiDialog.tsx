/**
 * Drone Wi-Fi — pick the network the drone's camera joins.
 *
 * Asked once after sign-in (App.tsx), and reachable any time from the account
 * menu and the Camera tab. Once saved, the network is re-sent to the drone on
 * every connection without asking again: the deck forgets it at power-off.
 *
 * The list is this laptop's own scan. Networks the drone cannot join — 5 GHz
 * only, or needing a username sign-in — are shown with the reason and cannot
 * be picked, so nobody types a password into something that will never work.
 * Without Location permission the OS hides every network name; the dialog then
 * asks for it, and typing the name is always available as the fallback.
 *
 * Modal conventions as FullScreenOverlay: Escape closes, focus moves in and
 * back, and the backdrop is inert to clicks.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { CameraWifi } from "@/lib/agent";
import {
  bandLabel,
  droneWifi,
  whyNotJoinable,
  type WifiNetwork,
  type WifiScan,
} from "@/lib/droneWifi";
import { Button, Message, Spinner, StatusDot, type Tone } from "@/components/ui";

/** How long to keep re-scanning after asking for permission, waiting for the
 *  operator to answer the OS prompt. */
const PERMISSION_WAIT_MS = 30_000;
const PERMISSION_POLL_MS = 1500;

type ScanLoad =
  | { kind: "scanning" }
  | { kind: "error"; message: string }
  | { kind: "ready"; scan: WifiScan };

const PHASE_TONE: Record<CameraWifi["phase"], Tone> = {
  "not-set": "idle",
  waiting: "idle",
  sending: "warning",
  joining: "warning",
  joined: "good",
  failed: "critical",
};

export function DroneWifiDialog({ onClose, wifi, onSaved }: {
  onClose: () => void;
  /** The agent's live account of the deck joining, if it has one. */
  wifi: CameraWifi | null;
  onSaved: (state: CameraWifi) => void;
}) {
  const [load, setLoad] = useState<ScanLoad>({ kind: "scanning" });
  const [saved, setSaved] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [typing, setTyping] = useState(false);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  const scan = useCallback(async (quiet = false) => {
    if (!quiet) setLoad({ kind: "scanning" });
    try {
      const result = await droneWifi.scan();
      setLoad({ kind: "ready", scan: result });
      // Pre-select the network this laptop is on, when the drone can join it:
      // the drone and the laptop must share a network for frames to arrive.
      setChosen((current) => {
        if (current) return current;
        const here = result.networks.find((n) => n.current && whyNotJoinable(n) === null);
        return here?.ssid ?? "";
      });
      return result;
    } catch (e) {
      setLoad({ kind: "error", message: String(e) });
      return null;
    }
  }, []);

  useEffect(() => {
    void scan();
    droneWifi.saved().then(setSaved).catch(() => setSaved(null));
  }, [scan]);

  // Modal focus and Escape.
  useEffect(() => {
    opener.current = document.activeElement;
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, [onClose]);

  const permission = load.kind === "ready" ? load.scan.permission : null;
  const namesHidden = permission !== null && permission !== "granted";
  const manual = typing || namesHidden || (load.kind === "ready" && load.scan.networks.length === 0);

  const askPermission = async () => {
    setAsking(true);
    await droneWifi.requestPermission().catch(() => undefined);
    // The OS prompt answers asynchronously; re-scan until names appear.
    const deadline = Date.now() + PERMISSION_WAIT_MS;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, PERMISSION_POLL_MS));
      const result = await scan(true);
      if (result && result.permission !== "undetermined") break;
    }
    setAsking(false);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const ssid = chosen.trim();
    if (!ssid) {
      setError("Choose a network, or type its name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const state = await droneWifi.save(ssid, password);
      setSaved(ssid);
      setPassword("");
      onSaved(state);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    setBusy(true);
    setError(null);
    try {
      await droneWifi.forget();
      setSaved(null);
      onSaved({ ssid: null, phase: "not-set", ip: null, message: null });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drone-wifi-title"
        className="flex max-h-full w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg"
      >
        <div className="border-b border-[var(--border)] px-5 py-4">
          <h2 id="drone-wifi-title" className="text-lg font-semibold">Drone Wi-Fi</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            The drone&apos;s camera joins this network, so video reaches this laptop while it
            stays online. Choose the network this laptop is on.
          </p>
        </div>

        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto px-5 py-4">
            {wifi && wifi.phase !== "not-set" && (
              <p role="status" className="text-sm">
                <StatusDot tone={PHASE_TONE[wifi.phase]}>
                  {wifi.message ?? wifi.phase}
                </StatusDot>
              </p>
            )}

            {saved && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm">
                <span>Saved: <strong className="font-semibold">{saved}</strong></span>
                <button
                  type="button"
                  onClick={() => void forget()}
                  disabled={busy}
                  className="min-h-11 px-2 text-sm font-medium text-[var(--status-critical)] disabled:opacity-50"
                >
                  Forget
                </button>
              </div>
            )}

            {load.kind === "scanning" && <Spinner label="Looking for Wi-Fi networks…" />}

            {load.kind === "error" && (
              <div className="grid gap-2">
                <Message tone="critical" text={load.message} />
                <div><Button onClick={() => void scan()}>Scan again</Button></div>
              </div>
            )}

            {permission === "undetermined" && (
              <div className="grid gap-2 rounded-lg border border-[var(--border)] px-3 py-3 text-sm">
                <p>
                  Your computer hides Wi-Fi network names until CropWatcher is allowed to see
                  them. It asks under Location — your location is not used.
                </p>
                <div>
                  <Button onClick={() => void askPermission()} disabled={asking}>
                    {asking ? "Waiting for your answer…" : "Show network names"}
                  </Button>
                </div>
              </div>
            )}

            {permission === "denied" && (
              <p className="text-sm text-[var(--muted)]">
                Network names are hidden. To list them, allow CropWatcher under Location
                Services in your system settings — or type the name below.
              </p>
            )}

            {load.kind === "ready" && !manual && (
              <fieldset className="grid gap-1">
                <legend className="eyebrow mb-1">Networks near this laptop</legend>
                {load.scan.networks.map((network) => (
                  <NetworkRow
                    key={network.ssid}
                    network={network}
                    checked={chosen === network.ssid}
                    onChoose={() => { setChosen(network.ssid); setError(null); }}
                  />
                ))}
              </fieldset>
            )}

            {manual && load.kind === "ready" && (
              <label className="grid gap-1 text-sm">
                <span className="font-medium">Network name</span>
                <input
                  value={chosen}
                  onChange={(e) => setChosen(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={32}
                  className="min-h-11 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3"
                />
              </label>
            )}

            {load.kind === "ready" && (
              <div className="flex flex-wrap gap-x-4 text-sm">
                {!namesHidden && (
                  <button type="button" onClick={() => setTyping((v) => !v)}
                    className="min-h-11 font-medium text-[var(--primary)]">
                    {typing ? "Pick from the list" : "Type a name instead"}
                  </button>
                )}
                <button type="button" onClick={() => void scan()}
                  className="min-h-11 font-medium text-[var(--primary)]">
                  Scan again
                </button>
              </div>
            )}

            <label className="grid gap-1 text-sm">
              <span className="font-medium">Password</span>
              <div className="flex gap-2">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="off"
                  maxLength={63}
                  className="min-h-11 min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-pressed={showPassword}
                  className="min-h-11 rounded-lg border border-[var(--border)] px-3 text-sm"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              <span className="text-[var(--muted)]">Leave it empty for an open network.</span>
            </label>

            <p className="text-sm text-[var(--muted)]">
              The password is saved in this computer&apos;s secure store and sent to the drone over
              its radio, which is not encrypted. Use a phone hotspot or a network set up for the
              drone — not your home Wi-Fi.
            </p>

            {error && <Message tone="critical" text={error} />}
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border)] px-5 py-3">
            <Button onClick={onClose}>{saved ? "Close" : "Not now"}</Button>
            <Button type="submit" variant="primary" disabled={busy || load.kind === "scanning"}>
              {busy ? "Saving…" : saved ? "Save and resend" : "Connect drone"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function NetworkRow({ network, checked, onChoose }: {
  network: WifiNetwork;
  checked: boolean;
  onChoose: () => void;
}) {
  const reason = whyNotJoinable(network);
  const detail = [
    bandLabel(network.bands),
    network.security === "open" ? "open" : network.security === "personal" ? "password" : null,
    network.current ? "this laptop" : null,
  ].filter(Boolean).join(" · ");

  return (
    <label
      className={`flex min-h-11 items-start gap-3 rounded-lg px-2 py-2 ${
        reason ? "cursor-not-allowed" : "cursor-pointer hover:bg-[var(--surface-2)]"
      }`}
    >
      <input
        type="radio"
        name="drone-network"
        checked={checked}
        disabled={reason !== null}
        onChange={onChoose}
        className="mt-1"
      />
      <span className="min-w-0 flex-1">
        <span className={`block wrap-anywhere text-sm font-medium ${reason ? "text-[var(--muted)]" : ""}`}>
          {network.ssid}
        </span>
        {detail && <span className="block text-xs text-[var(--muted)]">{detail}</span>}
        {reason && <span className="block text-xs text-[var(--muted)]">{reason}</span>}
      </span>
    </label>
  );
}
