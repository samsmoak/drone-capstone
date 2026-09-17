/**
 * Home: what the operator sees when the app opens.
 *
 * Two questions, answered before anything else is offered:
 *
 *   1. **Is everything ready?** — the agent, the account, the drone, the data.
 *   2. **What do I do next?** — one highlighted step, not a menu of six pages.
 *
 * The steps mirror the agent's own state machine (`session.py`), so this page
 * cannot get out of step with what the agent will actually allow: it reads the
 * state it is already being sent rather than tracking progress of its own.
 */

import type { Page } from "@/App";
import type { Mode, Session, SyncStatus, Telemetry } from "@/lib/agent";
import { SignIn } from "@/pages/control/ControlPage";
import { Button, PageHeader, Panel, Stat, StatusDot } from "@/components/ui";

type Props = {
  session: Session | null;
  telemetry: Telemetry | null;
  sync: SyncStatus | null;
  connected: boolean;
  run: (action: () => Promise<unknown>) => Promise<void>;
  onGo: (page: Page) => void;
};

/**
 * How far the session has got, as a number the steps below can compare against.
 * `checks_failed` sits at the same stage as `starting` — the checks are still
 * the thing in front of you.
 */
const PROGRESS: Record<Session["state"], number> = {
  signed_out: 0,
  idle: 1,
  starting: 2,
  checks_failed: 2,
  awaiting_confirmation: 3,
  ready: 4,
  busy: 4,
  ending: 4,
};

type Step = { title: string; detail: string };

function steps(mode: Mode): Step[] {
  return [
    {
      title: "Sign in",
      detail:
        "With your CropWatcher account — the same one as the web dashboard. " +
        "Every flight is recorded against the person who flew it.",
    },
    {
      title: "Start the session",
      detail: "Connects to the drone over the radio and reads who it is.",
    },
    {
      title: "Let the checks run",
      detail:
        "Radio, motors, battery, positioning and a still drone. Nothing arms " +
        "until they pass — keep the drone still while they run. After a crash, " +
        "Retry runs them all again.",
    },
    {
      title: "Confirm the area is clear",
      detail: "The drone on the floor, nothing above it, and everyone nearby told.",
    },
    mode === "auto"
      ? {
          title: "Run the battery & motor test, then Hover test",
          detail:
            "The test spins each motor on the ground and checks the battery under " +
            "load. Hover test rises, holds a steady height, and lands where it started.",
        }
      : {
          title: "Press Start, then hold W to rise",
          detail:
            "Run the battery & motor test first. Start turns the propellers gently " +
            "on the ground; the drone only leaves it while you hold W.",
        },
  ];
}

/** "Welcome back, Ada" — or just "Welcome back": the account row carries the
 *  email, and repeating it in a title reads as a mistake. */
function greeting(session: Session | null): string {
  const operator = session?.operator;
  if (!operator) return "CropWatcher flight control";
  const name = operator.name && operator.name !== operator.email ? operator.name : null;
  return name ? `Welcome back, ${name}` : "Welcome back";
}

export function HomePage({ session, telemetry, sync, connected, run, onGo }: Props) {
  // After an abnormal end the next thing in front of the operator is the checks
  // again, not flying — Retry puts them back there.
  const progress = session
    ? session.state === "ready" && session.retry_required ? PROGRESS.starting : PROGRESS[session.state]
    : 0;
  const mode = session?.mode ?? "auto";
  const vbat = telemetry?.values["pm.vbat"] ?? session?.drone?.battery_v ?? null;
  const pending = sync ? sync.pending_flights + sync.pending_events : 0;

  return (
    <div className="grid gap-6">
      <PageHeader title={greeting(session)}>
        This computer holds the radio, so this is the only app that can fly the
        drone. It records every flight and uploads it to the dashboard.
      </PageHeader>

      {session?.state === "signed_out" && <SignIn run={run} />}

      <section aria-label="Status" className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat
          label="Flight agent"
          value={connected ? "Running" : "Not running"}
          tone={connected ? "good" : "critical"}
          hint={connected ? "On this computer" : "Restart CropWatcher"}
        />
        <Stat
          label="Signed in"
          className="col-span-2"
          value={session?.operator?.email ?? "No one"}
          fit
          tone={session?.operator ? "good" : "warning"}
          hint={session?.operator ? "Flights recorded to this account" : "Required before flying"}
        />
        <Stat
          label="Drone"
          value={session?.drone?.hardware_id ?? "Not connected"}
          tone={session?.drone ? "good" : "idle"}
          hint={session?.drone ? "Connected over the radio" : "Connects when a session starts"}
        />
        <Stat
          label="Battery"
          value={vbat}
          unit="V"
          digits={2}
          tone={vbat == null ? "idle" : vbat < 3.75 ? "warning" : "good"}
          hint={
            vbat == null
              ? "Read once connected"
              : vbat < 3.75
                ? "Below the arming threshold — charge it"
                : "Enough to arm"
          }
        />
      </section>

      <Panel
        title="What to do next"
        note={`In ${mode === "auto" ? "Auto" : "Manual"} mode. Switch at the top — the steps up to the last one are the same either way.`}
        action={<Button variant="primary" onClick={() => onGo("control")}>Open Control</Button>}
      >
        <ol className="grid gap-3">
          {steps(mode).map((step, index) => {
            const done = index < progress;
            const current = index === progress;
            return (
              <li
                key={step.title}
                aria-current={current ? "step" : undefined}
                className={`flex gap-3 rounded-lg border p-3 ${
                  current
                    ? "border-[var(--primary)] bg-[var(--surface-2)]"
                    : "border-transparent"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${
                    done
                      ? "border-[var(--status-good)] text-[var(--status-good)]"
                      : current
                        ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
                        : "border-[var(--border)] text-[var(--muted)]"
                  }`}
                >
                  {done ? "✓" : index + 1}
                </span>
                <div>
                  <p className={done ? "text-sm text-[var(--muted)]" : "text-sm font-medium"}>
                    {step.title}
                    {done && <span className="sr-only"> — done</span>}
                  </p>
                  <p className="text-sm text-[var(--muted)]">{step.detail}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Before you fly">
          <ul className="grid gap-2 text-sm">
            <li>The Crazyradio dongle is in a USB port on this computer.</li>
            <li>The drone has a charged battery and is switched on, on the floor.</li>
            <li>
              The Lighthouse base stations are powered and their geometry is set for
              this room. <strong>Received</strong> matters, not stored — see{" "}
              <button
                type="button"
                onClick={() => onGo("positioning")}
                className="underline underline-offset-2"
              >
                Positioning
              </button>
              .
            </li>
            <li>Propellers are undamaged and the battery holds up. The battery &amp; motor test on Control checks both.</li>
          </ul>
        </Panel>

        <Panel title="Stopping it">
          <dl className="grid gap-3 text-sm">
            <div>
              <dt className="font-medium">
                Land <kbd className="rounded border border-[var(--border)] px-1 text-xs">L</kbd>
              </dt>
              <dd className="text-[var(--muted)]">
                The normal way down: it descends and settles under control. Always in
                the top bar while a session is running.
              </dd>
            </div>
            <div>
              <dt className="font-medium">Emergency stop — hold for one second</dt>
              <dd className="text-[var(--muted)]">
                Cuts the motors immediately, so the drone drops. For when it is stuck
                or heading somewhere it must not. No keyboard shortcut, deliberately.
              </dd>
            </div>
            <div>
              <dt className="font-medium">It also lands itself</dt>
              <dd className="text-[var(--muted)]">
                On low battery, lost positioning, drift or a tumble — and if this
                window stops answering.
              </dd>
            </div>
          </dl>
        </Panel>
      </div>

      <Panel
        title="Flight data"
        action={
          pending === 0 ? (
            <StatusDot tone="good">Everything uploaded</StatusDot>
          ) : (
            <StatusDot tone="warning">{pending} to upload</StatusDot>
          )
        }
      >
        <p className="text-sm text-[var(--muted)]">
          Readings are written to a file on this computer as they arrive, then
          uploaded to the dashboard. A flight can finish with no internet — it
          uploads when you are back online, and closing the app does not lose it.
          {sync?.last_error && ` Last upload attempt: ${sync.last_error}`}
        </p>
      </Panel>
    </div>
  );
}
