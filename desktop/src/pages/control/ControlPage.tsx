/**
 * Control: sign in, run the checks, confirm the area, then fly.
 *
 * TWO COLUMNS, above the `lg` breakpoint:
 *
 *   left   the console — how the drone is sitting, what we asked it to do, what
 *          it is reporting, what it can see, and where it is in the room
 *   right  the controls — the action rail, then whatever this step allows
 *
 * Below `lg` they stack, controls first: at the window's 720 px minimum width
 * (tauri.conf.json) two halves would be about 230 px each, which is unusable.
 * The controls are first in the DOM for that reason and ordered back to the
 * right on wide screens.
 *
 * The order of the flow is deliberate and the agent enforces it too — this page
 * only shows what is possible at each step:
 *
 *   signed out → idle → checks → confirm the area → ready → flying
 *
 * A flight that ends abnormally (a tumble, a guard, an emergency stop) puts
 * Retry in place of the flying controls: every check again, in this session,
 * before anything can fly — the drone holds its motors after a tumble.
 *
 * Auto shows the preset programs; Manual shows arming and the keys. Both run
 * the same checks and need the same confirmation, because the risk is the same.
 */

import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from "react";
import type { History, Run } from "@/App";
import { api, KEY_LABELS, type HealthTest, type Intent, type Session, type Telemetry } from "@/lib/agent";
import type { LogLine } from "@/lib/commandLog";
import { RecentSessions } from "@/pages/sessions/RecentSessions";
import { Button, Message, PageHeader, Panel, Spinner, Stat, StatusDot } from "@/components/ui";
import { ConsolePane } from "./ConsolePane";

type Props = {
  session: Session | null;
  telemetry: Telemetry | null;
  history: History;
  intent: Intent;
  flying: boolean;
  run: Run;
  logLines: LogLine[];
  onClearLog: () => void;
  historyKey: string;
  onOpenSession: (id: string) => void;
  onOpenSessions: () => void;
};

export function ControlPage({
  session, telemetry, history, intent, run, logLines, onClearLog,
  historyKey, onOpenSession, onOpenSessions,
}: Props) {
  if (session === null) {
    return <Spinner label="Connecting to the flight agent…" />;
  }

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow={session.mode === "auto" ? "Auto" : "Manual"}
        title="Control"
      >
        {session.mode === "auto"
          ? "Preset programs the drone flies by itself, with the safety guards running throughout."
          : session.assisted
            ? "You fly it with the keyboard. The drone still holds its own height and still lands itself on a fault."
            : "You fly it with the keyboard. With no base stations the drone holds its height on the barometer — roughly — and does not hold its position. It still lands itself on low battery, a tumble, or if this window stops answering."}
      </PageHeader>

      {session.message && (
        <Message
          tone={session.state === "checks_failed" ? "critical" : session.retry_required ? "warning" : "idle"}
          text={session.message}
        />
      )}

      {/* Signed out there is no drone and no stream, so the console would be
          a screen-and-a-half of empty terminal beside a sign-in form. The
          split starts once there is something to observe. */}
      {session.state === "signed_out" ? (
        <div className="max-w-md">
          <ControlColumn session={session} telemetry={telemetry} intent={intent} run={run} />
        </div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-2">
          {/* Controls first in the DOM, right-hand on wide screens. */}
          <div className="grid gap-5 lg:order-2">
            <ControlColumn session={session} telemetry={telemetry} intent={intent} run={run} />
          </div>
          <div className="lg:order-1">
            <ConsolePane
              session={session}
              telemetry={telemetry}
              history={history}
              logLines={logLines}
              onClearLog={onClearLog}
            />
          </div>
        </div>
      )}

      {session.state !== "signed_out" && (
        <RecentSessions refreshKey={historyKey} mode={session.mode} onOpen={onOpenSession} onOpenAll={onOpenSessions} />
      )}
    </div>
  );
}

// ── the right column ─────────────────────────────────────────────────

function ControlColumn({ session, telemetry, intent, run }: {
  session: Session;
  telemetry: Telemetry | null;
  intent: Intent;
  run: Run;
}) {
  // The flight parameters live here, not inside a panel, because the action
  // rail's Hover demo button is their trigger and the ambient temperature is
  // shared with arming in Manual.
  const [height, setHeight] = useState("0.30");
  const [hold, setHold] = useState("10");
  const [ambient, setAmbient] = useState("22C");

  const ready = session.state === "ready" && !session.retry_required;
  const showFlightControls =
    (session.state === "ready" || session.state === "busy") && !session.retry_required;

  return (
    <>
      <ActionRail
        session={session}
        run={run}
        ready={ready}
        height={height}
        hold={hold}
        ambient={ambient}
      />

      {session.state === "signed_out" && <SignIn run={run} />}
      {(session.state === "starting" || session.state === "checks_failed" ||
        session.state === "awaiting_confirmation") && (
        <Checklist session={session} run={run} />
      )}
      {session.state === "ready" && session.retry_required && <RetryPanel run={run} />}

      {showFlightControls && (
        <>
          {session.health_test && <HealthTestPanel result={session.health_test} />}
          {session.mode === "auto" ? (
            <AutoControls
              session={session}
              height={height} setHeight={setHeight}
              hold={hold} setHold={setHold}
              ambient={ambient} setAmbient={setAmbient}
            />
          ) : (
            <ManualControls
              session={session} telemetry={telemetry} intent={intent}
              ambient={ambient} setAmbient={setAmbient}
            />
          )}
        </>
      )}

      {session.state === "ending" && (
        <Panel title="Ending the session">
          <Spinner label="Landing if needed, saving the flight, and uploading what is left…" />
        </Panel>
      )}

      {session.drone && <DroneSummary session={session} telemetry={telemetry} />}
    </>
  );
}

/**
 * The four things an operator presses, always in the same order and the same
 * place, whatever step the session is on.
 *
 * A control that cannot act right now is DISABLED WITH THE REASON, never hidden
 * and never silently dead (WCAG 2.2 AA, and Apple HIG on the same point). The
 * old page hid each of these until its step arrived, which meant the operator
 * relearned the layout at every stage.
 *
 * Slot two follows the mode: a Hover demo button in Manual would be permanently
 * disabled, which is worse than showing the thing Manual actually needs.
 */
function ActionRail({ session, run, ready, height, hold, ambient }: {
  session: Session;
  run: Run;
  ready: boolean;
  height: string;
  hold: string;
  ambient: string;
}) {
  const busy = session.state === "busy";
  const inSession = !["signed_out", "idle"].includes(session.state);

  /** Why this cannot be pressed — the agent's own constraints, in order. */
  const flightReason = (): string | null => {
    if (session.state === "signed_out") return "Sign in first — flights are recorded against a person.";
    if (session.state === "idle") return "Start the session first.";
    if (session.state === "starting") return "The checks are still running.";
    if (session.state === "checks_failed") return "The checks did not pass.";
    if (session.state === "awaiting_confirmation") return "Confirm the area is clear first.";
    if (session.state === "ending") return "The session is ending.";
    if (session.retry_required) return "Retry the checks — the last flight ended early.";
    if (busy) return "The drone is already flying. Land it first.";
    return null;
  };

  const modeSlot: RailAction = session.mode === "auto"
    ? {
        label: "Hover demo",
        variant: "primary",
        disabled: !ready || !session.assisted,
        reason: !session.assisted && flightReason() === null
          ? "The drone cannot see the base stations, so a preset flight would fly blind. Switch to Manual, or get the stations seen and start again."
          : flightReason(),
        onClick: () => void run(
          () => api.runProgram(Number(height), Number(hold), ambient),
          `Hover demo — ${height} m for ${hold} s`,
        ),
      }
    : {
        label: session.activity === "manual" ? "Motors running" : "Start motors",
        variant: "primary",
        disabled: !ready || session.activity === "manual",
        reason: session.activity === "manual"
          ? "The propellers are already turning. Hold W to rise."
          : flightReason(),
        onClick: () => void run(() => api.armManual(ambient), "Start motors"),
      };

  const actions: RailAction[] = [
    {
      label: session.activity === "health_test"
        ? "Testing…"
        : session.health_test ? "Test again" : "Battery & motor test",
      disabled: !ready,
      reason: flightReason(),
      // ONE trigger, because the agent runs both tests in one call
      // (POST /session/health-test). Two buttons that fired the same request
      // would be a lie; the results below are split into two tiles instead.
      onClick: () => void run(api.healthTest, "Battery & motor test"),
    },
    modeSlot,
    {
      label: session.state === "starting" ? "Starting…" : "Start session",
      disabled: session.state !== "idle",
      reason: session.state === "signed_out"
        ? "Sign in first — flights are recorded against a person."
        : inSession ? "A session is already running." : null,
      onClick: () => void run(api.start, "Start session"),
    },
    {
      label: "End session",
      variant: "danger",
      disabled: !inSession || busy || session.state === "ending",
      reason: !inSession
        ? "No session is running."
        : busy ? "Land the drone first (L)." : null,
      onClick: () => void run(api.endSession, "End session"),
    },
  ];

  const blocked = actions.filter((a) => a.disabled && a.reason);

  return (
    <Panel title="Actions">
      <div className="grid grid-cols-2 gap-2">
        {actions.map((action) => (
          <Button
            key={action.label}
            variant={action.variant ?? "secondary"}
            disabled={action.disabled}
            title={action.disabled ? action.reason ?? undefined : undefined}
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        ))}
      </div>
      {blocked.length > 0 && (
        // The tooltip is not enough on its own: it needs a hover, and an
        // operator wants to know why before reaching for the mouse.
        <ul className="mt-3 grid gap-1.5 text-xs text-[var(--muted)]">
          {blocked.map((action) => (
            <li key={action.label}>
              <span className="font-semibold text-[var(--foreground)]">{action.label}</span>
              {" — "}{action.reason}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

type RailAction = {
  label: string;
  onClick: () => void;
  disabled: boolean;
  reason?: string | null;
  variant?: "primary" | "secondary" | "danger";
};

// ── steps ────────────────────────────────────────────────────────────

export function SignIn({ run }: { run: Run }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    await run(() => api.signIn(email, password), `Sign in as ${email}`);
    setBusy(false);
  };

  return (
    <Panel
      title="Sign in"
      note="Flights are recorded against the person who flew them, so the drone will not arm until someone is signed in. Use your CropWatcher account."
    >
      <form onSubmit={submit} className="grid max-w-sm gap-3">
        <label className="grid gap-1 text-sm">
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
            className="min-h-10 border border-[var(--border)] bg-[var(--surface-2)] px-3"
          />
        </label>
        <label className="grid gap-1 text-sm">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="min-h-10 border border-[var(--border)] bg-[var(--surface-2)] px-3"
          />
        </label>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-xs leading-relaxed text-[var(--muted)]">
          Signing in needs an internet connection. You stay signed in on this
          computer until you sign out, and a flight can finish offline — its data
          uploads when you are back online.
        </p>
      </form>
    </Panel>
  );
}

function Checklist({ session, run }: { session: Session; run: Run }) {
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
      action={failed ? (
        session.session_id
          ? <Button variant="primary" onClick={() => void run(api.retry, "Retry the checks")}>Retry</Button>
          : <Button onClick={() => void run(api.start, "Start session")}>Try again</Button>
      ) : undefined}
    >
      {/* A fixed two-column grid: the status column is the same width for every
          row, so a check that finishes does not reflow the ones below it. */}
      <ol className="mono grid gap-1.5 text-xs">
        {session.checks.map((check) => (
          <li key={check.key} className="grid gap-x-3 gap-y-0.5 sm:grid-cols-[7rem_minmax(0,1fr)]">
            <span className="font-semibold uppercase tracking-[0.06em]">{check.label}</span>
            <span className="min-w-0 break-words text-[var(--muted)]">
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
        <div className="mt-5 grid gap-3 border border-[var(--status-warning)] p-4">
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              className="mt-0.5 h-5 w-5"
            />
            <span>
              The drone is on a flat surface, the area around and above it is
              clear, and everyone nearby knows it is about to fly.
            </span>
          </label>
          {unassisted && (
            <label className="flex items-start gap-3 bg-[var(--surface-2)] p-3 text-sm">
              <input
                type="checkbox"
                checked={acceptedUnassisted}
                onChange={(e) => setAcceptedUnassisted(e.target.checked)}
                className="mt-0.5 h-5 w-5"
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
              onClick={() => void run(
                () => api.confirmArea(unassisted),
                unassisted ? "Confirm the area (barometer)" : "Confirm the area",
              )}
            >
              {unassisted ? "Confirm and fly on the barometer" : "Confirm and continue"}
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}

// ── after an abnormal end ────────────────────────────────────────────

function RetryPanel({ run }: { run: Run }) {
  return (
    <Panel
      title="Check the drone again"
      note="The last flight ended early. After a tumble the drone holds its motors at zero, so a flight started now could report flying with nothing turning."
    >
      <div className="grid gap-4">
        <ol className="grid list-decimal gap-1.5 pl-5 text-sm">
          <li>Pick the drone up and look it over: propellers seated, nothing bent or loose.</li>
          <li>Stand it level on a flat surface, clear of anything it could hit.</li>
          <li>Press Retry. It frees the motors if the drone locked them, then runs every check again — the same steps as a new session, in this one.</li>
        </ol>
        <div>
          <Button variant="primary" onClick={() => void run(api.retry, "Retry the checks")}>
            Retry — check the drone again
          </Button>
        </div>
      </div>
    </Panel>
  );
}

// ── battery & motor test ─────────────────────────────────────────────

/**
 * The result of the drone's own two ground tests.
 *
 * Its trigger is in the action rail. The agent runs both tests in a single
 * call, so there is one button and TWO result tiles — the split the operator
 * wants is in the reading, not in the request.
 */
function HealthTestPanel({ result }: { result: HealthTest }) {
  const failed = new Set(result.motors.failed);
  return (
    <Panel
      title="Battery & motor test"
      action={
        <StatusDot tone={result.ok ? "good" : "critical"}>
          {result.ok ? "Passed" : "Did not pass"}
        </StatusDot>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="border border-[var(--border)] bg-[var(--surface-2)] p-3">
          <h3 className="eyebrow">Motors</h3>
          <ul className="mono mt-2 grid grid-cols-2 gap-1.5 text-xs">
            {[1, 2, 3, 4].map((motor) => (
              <li key={motor}>
                <StatusDot tone={failed.has(motor) ? "critical" : "good"}>
                  {`M${motor} ${failed.has(motor) ? "failed" : "passed"}`}
                </StatusDot>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs leading-relaxed text-[var(--muted)]">
            Each one spins briefly on its own, to find a bent propeller or a damaged motor.
          </p>
        </div>
        <div className="border border-[var(--border)] bg-[var(--surface-2)] p-3">
          <h3 className="eyebrow">Battery</h3>
          {result.battery ? (
            <div className="mt-2 grid gap-1 text-xs">
              <StatusDot tone={result.battery.passed ? "good" : "critical"}>
                {result.battery.passed ? "Holds up under load" : "Sags too far under load"}
              </StatusDot>
              <p className="mono text-[var(--muted)]">
                Sagged {result.battery.sag_v.toFixed(2)} V
                {result.battery.idle_vbat !== null && ` from ${result.battery.idle_vbat.toFixed(2)} V at rest`}
              </p>
            </div>
          ) : (
            <p className="mt-2 text-xs">
              <StatusDot tone="warning">{result.battery_error ?? "No result"}</StatusDot>
            </p>
          )}
          <p className="mt-2 text-xs leading-relaxed text-[var(--muted)]">
            All four run for a moment under load, to see how far the voltage sags. The
            drone does not take off — keep hands clear.
          </p>
        </div>
      </div>
    </Panel>
  );
}

// ── auto ─────────────────────────────────────────────────────────────

function AutoControls({ session, height, setHeight, hold, setHold, ambient, setAmbient }: {
  session: Session;
  height: string;
  setHeight: (v: string) => void;
  hold: string;
  setHold: (v: string) => void;
  ambient: string;
  setAmbient: (v: string) => void;
}) {
  const running = session.activity === "program";

  return (
    <Panel
      title="Hover demo"
      note="Rises straight up, holds a steady height, then lands where it started. The checks run again in the air: it lands by itself on low battery, lost positioning or drift."
    >
      {!session.assisted ? (
        <Message
          tone="warning"
          text="A preset flight needs the drone to know where it is, and it cannot see the base stations — it would fly blind. Switch to Manual in the sidebar to fly it by hand, or get the base stations seen and start the session again."
        />
      ) : running ? (
        <div className="grid gap-2">
          <Spinner label={`${session.flight?.phase ?? "flying"} ${session.flight?.detail ?? ""}`} />
          <p className="text-sm text-[var(--muted)]">
            Use <strong>Land</strong> at the top to come down early.
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Height (m)" value={height} onChange={setHeight}
                   type="number" step="0.05" min="0.1" max="1" />
            <Field label="Hold (s)" value={hold} onChange={setHold}
                   type="number" step="1" min="1" max="60" />
            <Field label="Room temp" value={ambient} onChange={setAmbient} hint="74F or 22C" />
          </div>
          <p className="text-xs text-[var(--muted)]">
            Press <strong>Hover demo</strong> in Actions above to fly it with these values.
          </p>
        </div>
      )}
    </Panel>
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
    <label className="grid gap-1 text-xs">
      <span className="eyebrow">{label}</span>
      <input
        {...input}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mono min-h-10 border border-[var(--border)] bg-[var(--surface-2)] px-2.5 text-sm"
      />
      {hint && <span className="text-[var(--muted)]">{hint}</span>}
    </label>
  );
}

// ── manual ───────────────────────────────────────────────────────────

function ManualControls({ session, telemetry, intent, ambient, setAmbient }: {
  session: Session;
  telemetry: Telemetry | null;
  intent: Intent;
  ambient: string;
  setAmbient: (v: string) => void;
}) {
  const armed = session.activity === "manual";
  const assisted = session.assisted;

  const note = assisted
    ? armed
      ? "The propellers are turning. Hold W to rise gently; let go and the drone holds its height."
      : "Start motors turns the propellers gently on the ground so you can see the drone is live. It only leaves the ground when you hold W."
    : armed
      ? "Barometer height hold: hold W to rise gently, let go and it holds that height (roughly — it wanders by tens of centimetres). It does not hold its position: use the arrows to correct drift."
      : "The drone cannot see the base stations, so height comes from the barometer. Start motors idles the propellers; hold W to lift off and rise gently. Land descends slowly to the floor.";

  return (
    <>
      {!assisted && session.unassisted_reason && (
        <Message tone="warning" text={`No base stations — height from the barometer, no position hold. ${session.unassisted_reason}`} />
      )}

      <Panel title={assisted ? "Manual flight" : "Manual flight — barometer height"} note={note}>
        {armed ? (
          <div className="flex flex-wrap items-center gap-5">
            <Stat label="Height" value={telemetry?.height_m ?? null} unit="m"
                  hint={assisted ? "From the base stations" : "From the barometer — approximate"} />
            <p className="text-sm text-[var(--muted)]">
              Use <strong>Land</strong> (or press <kbd>L</kbd>) to come down.
            </p>
          </div>
        ) : (
          <div className="grid max-w-[12rem] gap-3">
            <Field label="Room temp" value={ambient} onChange={setAmbient} hint="74F or 22C" />
            <p className="text-xs text-[var(--muted)]">
              Press <strong>Start motors</strong> in Actions above.
            </p>
          </div>
        )}
      </Panel>

      <Keypad intent={intent} />
    </>
  );
}

/**
 * Every binding, laid out where the keys actually are.
 *
 * THESE ARE NOT BUTTONS AND MUST NOT BECOME BUTTONS. The window reports which
 * keys are *held* and the agent runs the 50 Hz loop from that; a click has no
 * hold, so a clickable key would either do nothing or need a second control
 * path into the flight loop. They light from `intent`, which is the same state
 * the agent is being sent — so a key lit here is a key the drone knows about.
 */
function Keypad({ intent }: { intent: Intent }) {
  const land = KEY_LABELS.find((b) => b.keys.every((k) => !k.field));

  return (
    <Panel
      title="Keys"
      note="Every binding is on screen. A control surface whose keys are hidden is a crash waiting to happen."
    >
      <div className="flex flex-wrap items-start gap-8">
        <Cluster caption="Height and rotation">
          <div className="grid grid-cols-3 gap-1.5">
            <span />
            <Cap label="W" field="up" intent={intent} />
            <span />
            <Cap label="A" field="yaw_left" intent={intent} />
            <Cap label="S" field="down" intent={intent} />
            <Cap label="D" field="yaw_right" intent={intent} />
          </div>
          <Legend rows={[["W / S", "Rise / descend, gently"], ["A / D", "Rotate left / right"]]} />
        </Cluster>

        <Cluster caption="Position">
          <div className="grid grid-cols-3 gap-1.5">
            <span />
            <Cap label="↑" field="forward" intent={intent} />
            <span />
            <Cap label="←" field="left" intent={intent} />
            <Cap label="↓" field="back" intent={intent} />
            <Cap label="→" field="right" intent={intent} />
          </div>
          <Legend rows={[["↑ / ↓", "Forward / back"], ["← / →", "Left / right"]]} />
        </Cluster>

        {land && (
          <Cluster caption="Coming down">
            <Cap label="L" intent={intent} wide />
            <Legend rows={[["L", land.action]]} />
            <p className="mt-1 max-w-[11rem] text-xs leading-relaxed text-[var(--muted)]">
              Emergency stop is in the strip at the top and has no key: cutting the
              motors drops the drone.
            </p>
          </Cluster>
        )}
      </div>
    </Panel>
  );
}

function Cluster({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <p className="eyebrow">{caption}</p>
      {children}
    </div>
  );
}

/** A key cap. Square, and lit while the key is held. */
function Cap({ label, field, intent, wide = false }: {
  label: string;
  field?: keyof Intent;
  intent: Intent;
  wide?: boolean;
}) {
  const held = field ? intent[field] : false;
  return (
    <kbd
      className={`mono inline-flex h-10 items-center justify-center border border-b-[3px] text-sm font-semibold ${
        wide ? "w-20" : "w-10"
      } ${
        held
          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
          : "border-[var(--border)] bg-[var(--surface-2)]"
      }`}
    >
      {label}
      {/* The lit cap is the only on-screen sign that a key registered, so the
          state has to reach a screen reader as words. Not aria-pressed: this is
          not a button, and aria-pressed on a <kbd> is invalid. */}
      {held && <span className="sr-only"> held</span>}
    </kbd>
  );
}

function Legend({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="grid gap-0.5 text-xs">
      {rows.map(([keys, action]) => (
        <div key={keys} className="flex gap-2">
          <dt className="mono w-12 shrink-0 font-semibold">{keys}</dt>
          <dd className="text-[var(--muted)]">{action}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── shared ───────────────────────────────────────────────────────────

function DroneSummary({ session, telemetry }: { session: Session; telemetry: Telemetry | null }) {
  const vbat = telemetry?.values["pm.vbat"] ?? session.drone?.battery_v ?? null;
  return (
    <section aria-label="Drone" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Stat label="Drone" value={session.drone?.hardware_id ?? null} digits={0} fit />
      <Stat label="Battery" value={vbat} unit="V"
            tone={vbat == null ? undefined : vbat < 3.75 ? "warning" : "good"}
            hint={vbat != null && vbat < 3.75 ? "Below the arming threshold" : "Good"} />
      <Stat label="Height" value={telemetry?.height_m ?? null} unit="m"
            hint="Above the floor captured at takeoff" />
    </section>
  );
}
