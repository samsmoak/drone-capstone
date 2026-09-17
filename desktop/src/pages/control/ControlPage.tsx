/**
 * Control: sign in, run the checks, confirm the area, then fly.
 *
 * The order is deliberate and the agent enforces it too — this page only shows
 * what is possible at each step:
 *
 *   signed out → idle → checks → confirm the area → ready → flying
 *
 * Auto shows the preset programs; Manual shows arming and the keys. Both run
 * the same checks and need the same confirmation, because the risk is the same.
 */

import { useState, type FormEvent, type InputHTMLAttributes } from "react";
import { api, KEY_LABELS, type Intent, type Session, type Telemetry } from "@/lib/agent";
import { RecentSessions } from "@/pages/sessions/RecentSessions";
import { Button, Message, PageHeader, Panel, Spinner, Stat, StatusDot } from "@/components/ui";

type Props = {
  session: Session | null;
  telemetry: Telemetry | null;
  intent: Intent;
  flying: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
  historyKey: string;
  onOpenSession: (id: string) => void;
  onOpenSessions: () => void;
};

export function ControlPage({
  session, telemetry, intent, run, historyKey, onOpenSession, onOpenSessions,
}: Props) {
  if (session === null) {
    return <Spinner label="Connecting to the flight agent…" />;
  }
  const inSession = !["signed_out", "idle"].includes(session.state);

  return (
    <div className="grid gap-6">
      <PageHeader title={session.mode === "auto" ? "Control — Auto" : "Control — Manual"}>
        {session.mode === "auto"
          ? "Preset programs the drone flies by itself, with the safety guards running throughout."
          : session.assisted
            ? "You fly it with the keyboard. The drone still holds its own height and still lands itself on a fault."
            : "You fly it with the keyboard. With no base stations the drone holds its height on the barometer — roughly — and does not hold its position. It still lands itself on low battery, a tumble, or if this window stops answering."}
      </PageHeader>

      {session.message && (
        <Message
          tone={session.state === "checks_failed" ? "critical" : "idle"}
          text={session.message}
        />
      )}

      {session.state === "signed_out" && <SignIn run={run} />}
      {session.state === "idle" && <StartSession run={run} />}
      {(session.state === "starting" || session.state === "checks_failed" ||
        session.state === "awaiting_confirmation") && (
        <Checklist session={session} run={run} />
      )}
      {(session.state === "ready" || session.state === "busy") && (
        session.mode === "auto"
          ? <AutoControls session={session} run={run} />
          : <ManualControls session={session} telemetry={telemetry} intent={intent} run={run} />
      )}
      {session.state === "ending" && (
        <Panel title="Ending the session">
          <Spinner label="Landing if needed, saving the flight, and uploading what is left…" />
        </Panel>
      )}

      {session.drone && <DroneSummary session={session} telemetry={telemetry} />}

      {inSession && session.state !== "ending" && (
        <Panel
          title="End this session"
          note="Lands the drone if it is flying, closes the flight record, saves this session to the history and lets the upload finish. You can start a new session afterwards."
        >
          <Button
            variant="danger"
            disabled={session.state === "busy"}
            title={session.state === "busy" ? "Land first — the drone is flying" : undefined}
            onClick={() => void run(api.endSession)}
          >
            End session
          </Button>
          {session.state === "busy" && (
            <p className="mt-3 text-sm text-[var(--muted)]">
              The drone is flying. Land it first (L), or use End session in the top bar once it is down.
            </p>
          )}
        </Panel>
      )}

      {session.state !== "signed_out" && (
        <RecentSessions refreshKey={historyKey} mode={session.mode} onOpen={onOpenSession} onOpenAll={onOpenSessions} />
      )}
    </div>
  );
}

// ── steps ────────────────────────────────────────────────────────────

export function SignIn({ run }: { run: Props["run"] }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    await run(() => api.signIn(email, password));
    setBusy(false);
  };

  return (
    <Panel
      title="Sign in"
      note="Flights are recorded against the person who flew them, so the drone will not arm until someone is signed in. Use your CropWatcher account."
    >
      <form onSubmit={submit} className="grid max-w-sm gap-4">
        <label className="grid gap-1.5 text-sm">
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
            className="min-h-11 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3"
          />
        </label>
        <label className="grid gap-1.5 text-sm">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="min-h-11 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3"
          />
        </label>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-xs text-[var(--muted)]">
          Signing in needs an internet connection. You stay signed in on this
          computer until you sign out, and a flight can finish offline — its data
          uploads when you are back online.
        </p>
      </form>
    </Panel>
  );
}

function StartSession({ run }: { run: Props["run"] }) {
  return (
    <Panel
      title="Start a session"
      note="Connects to the drone and runs every check before anything can fly."
    >
      <Button variant="primary" onClick={() => void run(api.start)}>
        Start session
      </Button>
    </Panel>
  );
}

function Checklist({ session, run }: { session: Session; run: Props["run"] }) {
  const [confirmed, setConfirmed] = useState(false);
  const [acceptedUnassisted, setAcceptedUnassisted] = useState(false);
  const failed = session.state === "checks_failed";
  const awaiting = session.state === "awaiting_confirmation";
  // A positioning problem no longer blocks the flight — it costs the drone its
  // height hold. The operator is told exactly that, and confirms it separately.
  const unassisted = !session.assisted;
  const ready = confirmed && (!unassisted || acceptedUnassisted);

  return (
    <Panel
      title="Checks"
      note={session.state === "starting" ? "Keep the drone still while these run." : undefined}
      action={failed ? <Button onClick={() => void run(api.start)}>Try again</Button> : undefined}
    >
      <ol className="grid gap-2">
        {session.checks.map((check) => (
          <li key={check.key} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 text-sm">
            <span className="font-medium">{check.label}</span>
            <span className="min-w-0 text-[var(--muted)] sm:text-right">
              {check.status === "running" && <Spinner label={check.detail || "Checking…"} />}
              {check.status === "passed" && <StatusDot tone="good">{check.detail}</StatusDot>}
              {check.status === "warning" && <StatusDot tone="warning">{check.detail}</StatusDot>}
              {check.status === "failed" && <StatusDot tone="critical">{check.detail}</StatusDot>}
            </span>
          </li>
        ))}
        {session.checks.length === 0 && <Spinner label="Connecting to the drone…" />}
      </ol>

      {awaiting && (
        <div className="mt-6 grid gap-3 rounded-lg border border-[var(--status-warning)] p-4">
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-1 h-5 w-5"
            />
            <span>
              The drone is on a flat surface, the area around and above it is
              clear, and everyone nearby knows it is about to fly.
            </span>
          </label>
          {unassisted && (
            <label className="flex items-start gap-3 rounded-md bg-[var(--surface-2)] p-3 text-sm">
              <input
                type="checkbox"
                checked={acceptedUnassisted}
                onChange={(e) => setAcceptedUnassisted(e.target.checked)}
                className="mt-1 h-5 w-5"
              />
              <span>
                <strong>I will watch it closely.</strong> The drone cannot see the base
                stations, so its height comes from the barometer — it holds roughly,
                wandering by tens of centimetres — it will not hold its position, and it
                will not land itself on drift. Only Manual is available until the base
                stations are seen.
              </span>
            </label>
          )}
          <div>
            <Button
              variant="primary"
              disabled={!ready}
              onClick={() => void run(() => api.confirmArea(unassisted))}
            >
              {unassisted ? "Confirm and fly on the barometer" : "Confirm and continue"}
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}

// ── auto ─────────────────────────────────────────────────────────────

function AutoControls({ session, run }: { session: Session; run: Props["run"] }) {
  const [height, setHeight] = useState("0.30");
  const [hold, setHold] = useState("10");
  const [ambient, setAmbient] = useState("22C");
  const busy = session.state === "busy";
  const running = session.activity === "program";

  return (
    <>
      <Panel
        title="Start test"
        note="Spins each motor briefly and reports it — the fastest way to find a bent propeller or a motor damaged in a knock. The drone does not lift."
        action={
          session.prop_test && (
            <StatusDot tone={session.prop_test.ok ? "good" : "critical"}>
              {session.prop_test.ok
                ? "All four motors passed"
                : `Motor(s) ${(session.prop_test.failed ?? []).join(", ")} failed`}
            </StatusDot>
          )
        }
      >
        <Button onClick={() => void run(api.propTest)} disabled={busy}>
          {session.activity === "prop_test" ? "Testing…" : "Start test"}
        </Button>
      </Panel>

      <Panel
        title="Hover test"
        note="Rises straight up, holds a steady height, then lands where it started. The checks run again in the air: it lands by itself on low battery, lost positioning or drift."
      >
        {!session.assisted ? (
          <Message
            tone="warning"
            text="A preset flight needs the drone to know where it is, and it cannot see the base stations — it would fly blind. Switch to Manual at the top to fly it by hand, or get the base stations seen and start the session again."
          />
        ) : running ? (
          <div className="grid gap-3">
            <Spinner label={`${session.flight?.phase ?? "flying"} ${session.flight?.detail ?? ""}`} />
            <p className="text-sm text-[var(--muted)]">
              Use <strong>Land</strong> at the top to come down early.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto] sm:items-end">
            <Field label="Height above the floor (m)" value={height} onChange={setHeight}
                   type="number" step="0.05" min="0.1" max="1" />
            <Field label="Hold (s)" value={hold} onChange={setHold}
                   type="number" step="1" min="1" max="60" />
            <Field label="Room temperature" value={ambient} onChange={setAmbient}
                   hint="e.g. 74F or 22C" />
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => void run(() => api.runProgram(Number(height), Number(hold), ambient))}
            >
              Start hover test
            </Button>
          </div>
        )}
      </Panel>
    </>
  );
}

function Field({
  label, value, onChange, hint, ...input
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <label className="grid gap-1.5 text-sm">
      {label}
      <input
        {...input}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="tabular min-h-11 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3"
      />
      {hint && <span className="text-xs text-[var(--muted)]">{hint}</span>}
    </label>
  );
}

// ── manual ───────────────────────────────────────────────────────────

function ManualControls({
  session, telemetry, intent, run,
}: {
  session: Session;
  telemetry: Telemetry | null;
  intent: Intent;
  run: Props["run"];
}) {
  const [ambient, setAmbient] = useState("22C");
  const armed = session.activity === "manual";
  const assisted = session.assisted;

  const note = assisted
    ? armed
      ? "The propellers are turning. Hold W to rise gently; let go and the drone holds its height."
      : "Start turns the propellers gently on the ground so you can see the drone is live. It only leaves the ground when you hold W."
    : armed
      ? "Barometer height hold: hold W to rise gently, let go and it holds that height (roughly — it wanders by tens of centimetres). It does not hold its position: use the arrows to correct drift."
      : "The drone cannot see the base stations, so height comes from the barometer. Start idles the propellers; hold W to lift off and rise gently. Land descends slowly to the floor.";

  return (
    <>
      {!assisted && session.unassisted_reason && (
        <Message tone="warning" text={`No base stations — height from the barometer, no position hold. ${session.unassisted_reason}`} />
      )}
      <Panel title={assisted ? "Manual flight" : "Manual flight — barometer height"} note={note}>
        {armed ? (
          <div className="flex flex-wrap items-center gap-6">
            <Stat label="Height" value={telemetry?.height_m ?? null} unit="m"
                  hint={assisted ? "From the base stations" : "From the barometer — approximate"} />
            <p className="text-sm text-[var(--muted)]">
              Use <strong>Land</strong> (or press <kbd>L</kbd>) to come down.
            </p>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-4">
            <Field label="Room temperature" value={ambient} onChange={setAmbient}
                   hint="e.g. 74F or 22C" />
            <Button variant="primary" onClick={() => void run(() => api.armManual(ambient))}>
              Start
            </Button>
          </div>
        )}
      </Panel>

      <Panel title="Keys" note="Every binding is on screen. A control surface whose keys are hidden is a crash waiting to happen.">
        <dl className="grid gap-3 sm:grid-cols-2">
          {KEY_LABELS.map((binding) => (
            <div key={binding.action} className="flex items-center gap-4">
              <dt className="flex min-w-28 gap-1.5">
                {binding.keys.map((key) => {
                  const held = key.field ? intent[key.field] : false;
                  return (
                    <kbd
                      key={key.label}
                      className={`inline-flex h-9 min-w-9 items-center justify-center rounded-md border border-b-2 px-2 text-sm ${
                        held
                          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
                          : "border-[var(--border)] bg-[var(--surface-2)]"
                      }`}
                    >
                      {key.label}
                    </kbd>
                  );
                })}
              </dt>
              <dd className="text-[var(--muted)]">{binding.action}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </>
  );
}

// ── shared ───────────────────────────────────────────────────────────

function DroneSummary({ session, telemetry }: { session: Session; telemetry: Telemetry | null }) {
  const vbat = telemetry?.values["pm.vbat"] ?? session.drone?.battery_v ?? null;
  return (
    <section aria-label="Drone" className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Stat label="Drone" value={session.drone?.hardware_id ?? null} digits={0} />
      <Stat label="Battery" value={vbat} unit="V"
            tone={vbat == null ? undefined : vbat < 3.75 ? "warning" : "good"}
            hint={vbat != null && vbat < 3.75 ? "Below the arming threshold" : "Good"} />
      <Stat label="Height" value={telemetry?.height_m ?? null} unit="m"
            hint="Above the floor captured at takeoff" />
    </section>
  );
}
