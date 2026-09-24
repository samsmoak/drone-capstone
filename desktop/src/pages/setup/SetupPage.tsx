/**
 * Set up — from a drone out of the box to a session, in four steps.
 *
 * ONE LIST, ONE STEP OPEN. The step in front of the operator is open; finished
 * steps shrink to a line with a check; later steps are titles only. Words are
 * instructions, not explanations — the why lives in the docs (drone-wifi.txt,
 * camera.txt), not on the screen.
 *
 * Step 2 is the agent's drone_setup.py: it reads what the drone already has
 * (never assumes), installs only what is missing — drone firmware, camera,
 * camera Wi-Fi, in that order — then asks for the battery unplug the camera
 * needs, and only calls it done once the camera has started.
 */

import type { ReactNode } from "react";
import type { Page, Run } from "@/App";
import { api, type CameraWifi, type Session, type SetupState } from "@/lib/agent";
import { Button, Message, PageHeader, Spinner, StatusDot, type Tone } from "@/components/ui";

type Step = "connect" | "install" | "wifi" | "session";

export function SetupPage({ session, setup, wifi, run, onGo }: {
  session: Session | null;
  setup: SetupState | null;
  wifi: CameraWifi | null;
  run: Run;
  onGo: (page: Page) => void;
}) {
  const radio = session?.radio?.state;
  const installed = setup?.phase === "done";
  const connected = radio === "connected" || (setup !== null && setup.phase !== "idle"
    && setup.phase !== "failed" && setup.facts !== null);
  const wifiDone = wifi?.phase === "joined";
  const inSession = session?.session_id != null;

  const current: Step = !connected ? "connect" : !installed ? "install"
    : !wifiDone ? "wifi" : "session";
  const done = (s: Step) => ({
    connect: connected, install: installed, wifi: wifiDone, session: inSession,
  })[s];

  return (
    <div className="grid max-w-3xl gap-4">
      <PageHeader eyebrow="Operate" title="Set up" />
      <ol className="grid gap-2">
        <Item n={1} title="Connect the drone" done={done("connect")} open={current === "connect"}
              summary="Crazyradio plugged in, drone on">
          <p className="text-sm">Plug the Crazyradio into this laptop, then switch the drone on.</p>
          <p className="text-sm">
            <StatusDot tone={radio === "searching" ? "warning" : "idle"}>
              {session?.radio?.message ?? "Looking for the drone…"}
            </StatusDot>
          </p>
        </Item>

        <Item n={2} title="Install camera software" done={done("install")} open={current === "install"}
              summary="Drone firmware, camera and camera Wi-Fi installed">
          <Install setup={setup} run={run} busy={inSession} />
        </Item>

        <Item n={3} title="Connect the camera to Wi-Fi" done={done("wifi")} open={current === "wifi"}
              summary={wifi?.ssid ? `On ${wifi.ssid}` : "Connected"}>
          <p className="text-sm">Choose the Wi-Fi network this laptop is on. The drone joins it and the camera streams over it.</p>
          <div><Button variant="primary" onClick={() => onGo("wifi")}>Open Drone Wi-Fi</Button></div>
        </Item>

        <Item n={4} title="Start a session" done={done("session")} open={current === "session"}
              summary="Session running">
          <p className="text-sm">Everything is ready. Start a session to fly and record.</p>
          <div><Button variant="primary" onClick={() => onGo("home")}>Go to Home</Button></div>
        </Item>
      </ol>
    </div>
  );
}

function Install({ setup, run, busy }: { setup: SetupState | null; run: Run; busy: boolean }) {
  const phase = setup?.phase ?? "idle";
  const working = phase === "checking" || phase === "installing" || phase === "verifying";
  const battery = setup?.facts?.battery_v;
  const needsAny = setup ? Object.values(setup.parts).some((p) => p === "needed") : false;

  if (phase === "unplug") {
    // The one step only a person can do — alone, and large.
    return (
      <div className="grid gap-2 border-2 border-[var(--status-warning)] bg-[var(--surface)] p-4">
        <p className="text-base font-semibold">Unplug the drone&apos;s battery.</p>
        <p className="text-sm">Wait 10 seconds, then plug it back in. The camera needs a full power-off to start.</p>
        <Spinner label="Waiting for the drone to power off and come back…" />
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {busy && <Message tone="warning" text="End the session first — set up needs the radio." />}

      {setup && setup.order && Object.keys(setup.parts).length > 0 && (
        <ul className="grid border border-[var(--border)]">
          {setup.order.map((part) => {
            const status = setup.parts[part];
            const active = setup.current === part && phase === "installing";
            return (
              <li key={part} className="grid gap-1 border-b border-[var(--border)] px-3 py-2 last:border-b-0">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">{setup.labels[part]}</span>
                  <PartStatus status={status} active={active} progress={setup.progress} />
                </div>
                {active && (
                  <div className="h-1.5 w-full bg-[var(--surface-2)]" role="progressbar"
                       aria-valuenow={Math.round(setup.progress * 100)} aria-valuemin={0} aria-valuemax={100}
                       aria-label={`Installing ${setup.labels[part]}`}>
                    <div className="h-full bg-[var(--primary)] transition-[width] duration-300 motion-reduce:transition-none"
                         style={{ width: `${Math.round(setup.progress * 100)}%` }} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {battery != null && (
        <p className="text-xs text-[var(--muted)]">
          Battery {battery.toFixed(2)} V{battery < 3.8 ? " — charge it above 3.8 V before installing" : ""}
        </p>
      )}

      {working && <Spinner label={setup?.message ?? "Working…"} />}
      {phase === "failed" && setup?.message && <Message tone="critical" text={setup.message} />}
      {phase === "done" && setup?.message && <Message tone="good" text={setup.message} />}

      {!working && phase !== "done" && (
        <div className="flex flex-wrap items-center gap-2">
          {phase === "ready" && needsAny ? (
            <>
              <Button variant="primary" disabled={busy}
                      onClick={() => void run(api.setupInstall, "Install camera software")}>
                Install
              </Button>
              <span className="text-xs text-[var(--muted)]">About 5 minutes. Keep the drone on.</span>
            </>
          ) : (
            <Button variant="primary" disabled={busy}
                    onClick={() => void run(api.setupCheck, "Check the drone")}>
              {phase === "failed" ? "Try again" : "Check the drone"}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function PartStatus({ status, active, progress }: {
  status: string | undefined; active: boolean; progress: number;
}) {
  const [tone, label]: [Tone, string] = active ? ["warning", `${Math.round(progress * 100)}%`]
    : status === "installed" || status === "done" ? ["good", "Installed"]
    : status === "needed" ? ["idle", "To install"] : ["idle", "—"];
  return <span className="text-xs"><StatusDot tone={tone}>{label}</StatusDot></span>;
}

function Item({ n, title, done, open, summary, children }: {
  n: number; title: string; done: boolean; open: boolean; summary: string; children: ReactNode;
}) {
  return (
    <li
      aria-current={open ? "step" : undefined}
      className={`border bg-[var(--surface)] ${open ? "border-[var(--primary)]" : "border-[var(--border)]"}`}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <span
          aria-hidden="true"
          className={`mono flex h-6 w-6 shrink-0 items-center justify-center border text-xs font-bold ${
            done ? "border-[var(--status-good)] text-[var(--status-good)]"
              : open ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
              : "border-[var(--border)] text-[var(--muted)]"
          }`}
        >
          {done ? "✓" : n}
        </span>
        <span className="min-w-0 flex-1">
          <span className={`block text-sm font-semibold ${!open && !done ? "text-[var(--muted)]" : ""}`}>{title}</span>
          {done && !open && <span className="block text-xs text-[var(--muted)]">{summary}</span>}
        </span>
        {done && <span className="sr-only">done</span>}
      </div>
      {open && <div className="grid gap-3 border-t border-[var(--border)] px-4 py-3">{children}</div>}
    </li>
  );
}
