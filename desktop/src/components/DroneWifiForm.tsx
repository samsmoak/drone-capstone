/**
 * Choose the drone's Wi-Fi network — the picker both the sign-in dialog and
 * the Drone Wi-Fi page use, so the two cannot drift apart.
 *
 * MINIMAL ON PURPOSE (2026-09-24: "too much words and unnecessary bloat"). Only
 * networks the drone can join are listed; the rest fold into one line. The
 * password field appears only for a network that has one. One hint line, not
 * paragraphs.
 *
 * THE LIST ARRIVES IN TWO STEPS: the OS's last scan instantly, a live scan
 * behind it. A live scan alone was a 12.5-second spinner (MacBook Pro,
 * measured) that read as "stuck". Without Location permission the OS hides
 * every name; one button asks, and "Other network…" is always there.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { CameraWifi } from "@/lib/agent";
import {
  PASSWORD_MAX,
  bandLabel,
  droneWifi,
  shortWhyNot,
  whyNotJoinable,
  type WifiScan,
} from "@/lib/droneWifi";
import { Button, Message, StatusDot } from "@/components/ui";

/** How long to keep re-reading after asking for permission, while the operator
 *  answers the OS prompt. */
const PERMISSION_WAIT_MS = 30_000;
const PERMISSION_POLL_MS = 1500;

/** The pseudo-choice that turns the list into a text field. */
const OTHER = "\u0000other";

export function DroneWifiForm({ onSaved, onCancel, cancelLabel = "Cancel" }: {
  onSaved: (state: CameraWifi) => void;
  /** A second button, when the container offers a way out. */
  onCancel?: () => void;
  cancelLabel?: string;
}) {
  const [scan, setScan] = useState<WifiScan | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [chosen, setChosen] = useState("");
  const [typed, setTyped] = useState("");
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
    droneWifi.scan(false).then(apply).catch(() => undefined).finally(() => void refresh());
  }, [apply, refresh]);

  const permission = scan?.permission ?? null;
  const namesHidden = permission !== null && permission !== "granted";
  const all = scan?.networks ?? [];
  const joinable = all.filter((n) => whyNotJoinable(n) === null);
  const blocked = all.filter((n) => whyNotJoinable(n) !== null);
  const manual = chosen === OTHER || namesHidden;
  const picked = manual ? null : joinable.find((n) => n.ssid === chosen) ?? null;
  const name = (manual ? typed : chosen).trim();
  // A password field only when the network has one — or when it is typed and
  // nothing is known about it.
  const needsPassword = manual ? true : picked?.security === "personal";
  const here = all.find((n) => n.current)?.ssid ?? null;
  const elsewhere = here !== null && name !== "" && name !== here;

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
    if (!name) {
      setError("Choose a network.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const state = await droneWifi.save(name, needsPassword ? password : "");
      if (!mounted.current) return;
      setPassword("");
      onSaved(state);
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid gap-3">
      <div className="mono flex items-center justify-between gap-2 text-[10px] uppercase tracking-[0.08em] text-[var(--muted)]">
        <span>{scan === null ? "Looking for networks…" : refreshing ? "Networks · scanning…" : "Networks"}</span>
        <button type="button" onClick={() => void refresh()} disabled={refreshing}
          className="min-h-8 px-1 font-semibold hover:text-[var(--foreground)] disabled:opacity-50">
          Rescan
        </button>
      </div>

      {scanError && <Message tone="critical" text={scanError} />}

      {permission === "undetermined" && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>Network names are hidden.</span>
          <Button onClick={() => void askPermission()} disabled={asking}>
            {asking ? "Waiting…" : "Show names"}
          </Button>
        </div>
      )}
      {permission === "denied" && (
        <p className="text-xs text-[var(--muted)]">
          Names hidden — allow CropWatcher in Location Services to list them.
        </p>
      )}

      {scan !== null && !namesHidden && (
        <fieldset className="grid gap-0 border border-[var(--border)]">
          <legend className="sr-only">Network</legend>
          {joinable.map((network) => (
            <Row
              key={network.ssid}
              checked={chosen === network.ssid}
              onChoose={() => { setChosen(network.ssid); setError(null); }}
              title={network.ssid}
              detail={[
                bandLabel(network.bands),
                network.security === "open" ? "open" : null,
                network.current ? "this laptop" : null,
              ].filter(Boolean).join(" · ")}
            />
          ))}
          <Row
            checked={chosen === OTHER}
            onChoose={() => { setChosen(OTHER); setError(null); }}
            title="Other network…"
          />
        </fieldset>
      )}

      {blocked.length > 0 && !namesHidden && (
        <details className="text-xs text-[var(--muted)]">
          <summary className="min-h-8 cursor-pointer py-1">
            {blocked.length} network{blocked.length === 1 ? "" : "s"} the drone can&apos;t use
          </summary>
          <ul className="grid gap-0.5 pt-1">
            {blocked.map((n) => (
              <li key={n.ssid} title={whyNotJoinable(n) ?? undefined} className="flex justify-between gap-3">
                <span className="wrap-anywhere">{n.ssid}</span>
                <span className="shrink-0">{shortWhyNot(n)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {manual && (
        <input
          aria-label="Network name"
          placeholder="Network name"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          maxLength={32}
          className="min-h-11 border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
        />
      )}

      {needsPassword && name !== "" && (
        <div className="grid gap-1">
          <div className="flex gap-2">
            <input
              aria-label="Password"
              placeholder={manual ? "Password (empty if open)" : "Password"}
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
              maxLength={PASSWORD_MAX}
              className="min-h-11 min-w-0 flex-1 border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
            />
            <button type="button" onClick={() => setShowPassword((v) => !v)} aria-pressed={showPassword}
              className="mono min-h-11 border border-[var(--border)] px-3 text-[10px] font-semibold uppercase tracking-[0.08em]">
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          <p className="text-xs text-[var(--muted)]">
            Up to {PASSWORD_MAX} characters · sent over the drone&apos;s unencrypted radio — use a
            hotspot, not your home Wi-Fi.
          </p>
        </div>
      )}

      {elsewhere && (
        <p className="text-xs">
          <StatusDot tone="serious">This laptop is on {here}. The camera needs both on one network.</StatusDot>
        </p>
      )}

      {error && <Message tone="critical" text={error} />}

      <div className="flex flex-wrap justify-end gap-2">
        {onCancel && <Button onClick={onCancel}>{cancelLabel}</Button>}
        <Button type="submit" variant="primary" disabled={busy || name === ""}>
          {busy ? "Connecting…" : "Connect drone"}
        </Button>
      </div>
    </form>
  );
}

function Row({ checked, onChoose, title, detail }: {
  checked: boolean;
  onChoose: () => void;
  title: string;
  detail?: string;
}) {
  return (
    <label
      className={`flex min-h-11 cursor-pointer items-center gap-3 border-b border-[var(--border)] px-3 py-1.5 last:border-b-0 ${
        checked ? "bg-[var(--surface-2)] shadow-[inset_3px_0_0_var(--primary)]" : "hover:bg-[var(--surface-2)]"
      }`}
    >
      <input type="radio" name="drone-network" checked={checked} onChange={onChoose} />
      <span className="min-w-0 flex-1 wrap-anywhere text-sm font-medium">{title}</span>
      {detail && (
        <span className="mono shrink-0 text-[10px] uppercase tracking-[0.08em] text-[var(--muted)]">{detail}</span>
      )}
    </label>
  );
}
