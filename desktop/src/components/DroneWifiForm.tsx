/**
 * Choose the drone's Wi-Fi network — the picker both the sign-in dialog and
 * the Drone Wi-Fi page use, so the two cannot drift apart.
 *
 * THE LIST ARRIVES IN TWO STEPS. The OS's last scan answers instantly; a live
 * scan runs behind it and replaces it. A live scan alone was a 12.5-second
 * spinner (measured on a MacBook Pro, 2026-09-24) that read as "stuck".
 *
 * Networks the drone cannot join — 5 GHz only, enterprise sign-in — are shown
 * with the reason and cannot be picked. Without Location permission the OS
 * hides every name; the form asks for it, and typing is always the fallback.
 *
 * THE DRONE AND THIS LAPTOP MUST SHARE A NETWORK or no frame can arrive, so a
 * choice other than the laptop's current network is warned about, not refused:
 * the laptop may be about to move.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { CameraWifi } from "@/lib/agent";
import {
  PASSWORD_MAX,
  bandLabel,
  droneWifi,
  whyNotJoinable,
  type WifiNetwork,
  type WifiScan,
} from "@/lib/droneWifi";
import { Button, Message, Spinner } from "@/components/ui";

/** How long to keep re-reading after asking for permission, while the operator
 *  answers the OS prompt. */
const PERMISSION_WAIT_MS = 30_000;
const PERMISSION_POLL_MS = 1500;

export function DroneWifiForm({ onSaved, onCancel, cancelLabel }: {
  onSaved: (state: CameraWifi) => void;
  /** Shown as a second button when the container offers a way out. */
  onCancel?: () => void;
  cancelLabel?: string;
}) {
  const [scan, setScan] = useState<WifiScan | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [chosen, setChosen] = useState("");
  const [typing, setTyping] = useState(false);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const apply = useCallback((result: WifiScan) => {
    if (!mounted.current) return;
    setScan(result);
    setScanError(null);
    // Pre-select the laptop's own network when the drone can join it.
    setChosen((current) => {
      if (current) return current;
      const here = result.networks.find((n) => n.current && whyNotJoinable(n) === null);
      return here?.ssid ?? "";
    });
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      apply(await droneWifi.scan(true));
    } catch (e) {
      if (mounted.current) setScanError(String(e));
    } finally {
      if (mounted.current) setRefreshing(false);
    }
  }, [apply]);

  useEffect(() => {
    // Instant first, then the air behind it.
    droneWifi.scan(false).then(apply).catch(() => undefined).finally(() => void refresh());
    droneWifi.saved().then((s) => mounted.current && setSaved(s)).catch(() => undefined);
  }, [apply, refresh]);

  const permission = scan?.permission ?? null;
  const namesHidden = permission !== null && permission !== "granted";
  const listed = scan?.networks ?? [];
  const manual = typing || namesHidden || (scan !== null && !refreshing && listed.length === 0);
  const current = listed.find((n) => n.current)?.ssid ?? null;
  const elsewhere = current !== null && chosen.trim() !== "" && chosen.trim() !== current;

  const askPermission = async () => {
    setAsking(true);
    await droneWifi.requestPermission().catch(() => undefined);
    const deadline = Date.now() + PERMISSION_WAIT_MS;
    while (Date.now() < deadline && mounted.current) {
      await new Promise((r) => setTimeout(r, PERMISSION_POLL_MS));
      const result = await droneWifi.scan(false).catch(() => null);
      if (result) apply(result);
      if (result && result.permission !== "undetermined") break;
    }
    if (mounted.current) setAsking(false);
    void refresh();
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
      if (!mounted.current) return;
      setSaved(ssid);
      setPassword("");
      onSaved(state);
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const forget = async () => {
    setBusy(true);
    setError(null);
    try {
      await droneWifi.forget();
      if (!mounted.current) return;
      setSaved(null);
      onSaved({ ssid: null, phase: "not-set", ip: null, message: null });
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-4">
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

      {scan === null && !scanError && <Spinner label="Looking for Wi-Fi networks…" />}
      {scanError && <Message tone="critical" text={scanError} />}

      {permission === "undetermined" && (
        <div className="grid gap-2 rounded-lg border border-[var(--border)] px-3 py-3 text-sm">
          <p>
            Your computer hides Wi-Fi network names until CropWatcher may see them. It asks
            under Location — your location is not used.
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
          Network names are hidden. To list them, allow CropWatcher under Location Services in
          your system settings — or type the name below.
        </p>
      )}

      {scan !== null && !manual && (
        <fieldset className="grid gap-1">
          <legend className="eyebrow mb-1">
            Networks near this laptop{refreshing ? " · refreshing…" : ""}
          </legend>
          {listed.map((network) => (
            <NetworkRow
              key={network.ssid}
              network={network}
              checked={chosen === network.ssid}
              onChoose={() => { setChosen(network.ssid); setError(null); }}
            />
          ))}
        </fieldset>
      )}

      {scan !== null && manual && (
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

      {scan !== null && (
        <div className="flex flex-wrap gap-x-4 text-sm">
          {!namesHidden && (
            <button type="button" onClick={() => setTyping((v) => !v)}
              className="min-h-11 font-medium text-[var(--primary)]">
              {typing ? "Pick from the list" : "Type a name instead"}
            </button>
          )}
          <button type="button" onClick={() => void refresh()} disabled={refreshing}
            className="min-h-11 font-medium text-[var(--primary)] disabled:opacity-50">
            {refreshing ? "Scanning…" : "Scan again"}
          </button>
        </div>
      )}

      {elsewhere && (
        <Message
          tone="warning"
          text={`This laptop is on ${current}. The camera only reaches this laptop when both are on the same network.`}
        />
      )}

      <label className="grid gap-1 text-sm">
        <span className="font-medium">Password</span>
        <div className="flex gap-2">
          <input
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="off"
            maxLength={PASSWORD_MAX}
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
        <span className="text-[var(--muted)]">
          Leave it empty for an open network. The drone holds up to {PASSWORD_MAX} characters.
        </span>
      </label>

      <p className="text-sm text-[var(--muted)]">
        Saved in this computer&apos;s secure store and sent to the drone over its radio, which is
        not encrypted. Use a phone hotspot or a network set up for the drone — not your home
        Wi-Fi.
      </p>

      {error && <Message tone="critical" text={error} />}

      <div className="flex flex-wrap justify-end gap-2">
        {onCancel && <Button onClick={onCancel}>{cancelLabel ?? "Cancel"}</Button>}
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Saving…" : saved ? "Save and resend" : "Connect drone"}
        </Button>
      </div>
    </form>
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
