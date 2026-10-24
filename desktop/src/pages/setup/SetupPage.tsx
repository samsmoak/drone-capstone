/**
 * Set up — from a drone out of the box to a session.
 *
 * ONE LIST, ONE STEP OPEN. The step in front of the operator is open; finished
 * steps shrink to a line with a check; later steps are titles only. Words are
 * instructions, not explanations — the why lives in the docs (drone-wifi.txt,
 * camera.txt), not on the screen.
 *
 * Step 2 is the agent's drone_setup.py: it reads what the drone already has
 * (never assumes), installs only what is missing — drone firmware, the
 * positioning deck's firmware, camera, camera Wi-Fi, in that order — then asks
 * for the battery unplug the camera needs, and only calls it done once the
 * camera has started and the positioning deck kept its firmware.
 *
 * THE INSTALL RUNS IN A TERMINAL, not from a button (2026-10-24, Samuel): step
 * 2 checks the drone and lists its parts, then shows the command that writes
 * them — `cropwatcher setup`, this machine's exact line from GET /setup/command
 * — with a Copy button. DroneDeck is quit first: the radio has one owner, and
 * while the app is open its agent holds it. Reopened, "Check the drone" reads
 * the result.
 *
 * Step 2 holds the list only while it has something to do (see listed below).
 * Opened by its button it stays open once the check finds everything
 * installed, so any part can be ticked and written again ("Reinstall"). A
 * replaced AI deck needs no tick: the agent tells it apart by its factory
 * serial and lists its camera and Wi-Fi as to install (setup.txt). A tick adds
 * `--reinstall <parts>` to the command.
 *
 * Step 3 sets each base station's channel over its USB cable (agent
 * flight/basestation.py — Bitcraze's "Set BS channel"): every V2 station must
 * be on its own channel, 1 and 2 for a pair, or the drone reads the light and
 * the calibration but decodes no angles (measured 2026-10-05). It reads done
 * once the drone decodes angles.
 *
 * Measuring where the base station stands is NOT here: it is part of flying,
 * Control › Auto › ② Position, where the operator already is (2026-10-05 —
 * it sat here as step 4 and could not be found).
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Page, Run } from "@/App";
import {
  AgentError, api, type BaseStation, type CameraWifi, type Session, type SetupCommand, type SetupPart,
  type SetupState, type StationStatus,
} from "@/lib/agent";
import { StationStages, useStation } from "@/components/StationStages";
import { Button, Message, PageHeader, Spinner, StatusDot, type Tone } from "@/components/ui";

type Step = "connect" | "install" | "channels" | "wifi" | "session";

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
  const station = useStation(radio === "connected");
  // A step the operator opened by its button, over the one the list chose.
  const [opened, setOpened] = useState<Step | null>(null);
  // Decoding: the drone turns sweeps into angles — what the channels are for.
  // bsReceive is the firmware's own word for it (lighthouse_core.c sets it
  // only when a sweep yields angles); validAngles is not (2026-10-05).
  const decoding = station?.connected === true && station.received.length > 0
    && opened !== "channels";
  // Step 2 holds the list only while it has something to do. Its state is the
  // agent's and starts "idle" every launch — never checked this run is not the
  // same as missing, and it once hid step 3 from an operator whose drone was
  // fully installed (2026-10-05). "Check" opens it whenever it is wanted.
  const phase = setup?.phase ?? "idle";
  const installPending = ["checking", "installing", "verifying", "unplug", "failed"].includes(phase)
    || (phase === "ready" && setup !== null && Object.values(setup.parts).some((p) => p === "needed"));

  // An install that finishes hands over to the next step. A check that finds
  // everything installed does not: the operator opened step 2 to see it, or to
  // reinstall something, and closes it with its own button.
  const lastPhase = useRef(phase);
  useEffect(() => {
    const was = lastPhase.current;
    lastPhase.current = phase;
    if (opened === "install" && phase === "done" && ["installing", "unplug", "verifying"].includes(was)) {
      setOpened(null);
    }
  }, [opened, phase]);

  const listed: Step = !connected ? "connect" : installPending ? "install"
    : !decoding ? "channels" : !wifiDone ? "wifi" : "session";
  const current: Step = connected && opened !== null ? opened : listed;
  const done = (s: Step) => ({
    connect: connected, install: installed, channels: decoding, wifi: wifiDone, session: inSession,
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

        <Item n={2} title="Install drone software" done={done("install")} open={current === "install"}
              summary="Drone firmware, positioning deck, camera and camera Wi-Fi installed"
              onReopen={() => setOpened("install")} reopenLabel="Check or reinstall">
          <Install setup={setup} run={run} busy={inSession} onClose={() => setOpened(null)} />
        </Item>

        <Item n={3} title="Base stations: one channel each" done={done("channels")} open={current === "channels"}
              summary="The drone decodes the base station's sweeps"
              onReopen={() => setOpened("channels")} reopenLabel={done("channels") ? "Check again" : "Set"}>
          <Channels station={station} run={run} onDone={() => setOpened(null)} />
        </Item>

        <Item n={4} title="Connect the camera to Wi-Fi" done={done("wifi")} open={current === "wifi"}
              summary={wifi?.ssid ? `On ${wifi.ssid}` : "Connected"}>
          <p className="text-sm">Choose the Wi-Fi network this laptop is on. The drone joins it and the camera streams over it.</p>
          <div><Button variant="primary" onClick={() => onGo("wifi")}>Open Drone Wi-Fi</Button></div>
        </Item>

        <Item n={5} title="Fly" done={done("session")} open={current === "session"}
              summary="Session running">
          <p className="text-sm">The drone is set up. In Control › Auto, ② Position measures where the base station stands from where the drone sits, then the flyable space, the plan, and Fly.</p>
          <div><Button variant="primary" onClick={() => onGo("control")}>Go to Control</Button></div>
        </Item>
      </ol>
    </div>
  );
}

/** The AI deck's two chips are recorded as one bundle, so they are ticked together. */
const DECK_PARTS: SetupPart[] = ["camera", "wifi"];

/** The install command for this machine, from the agent: loading, failed with
 *  a retry, or the line. */
function useSetupCommand(given?: SetupCommand) {
  const [cmd, setCmd] = useState<SetupCommand | null>(given ?? null);
  const [failed, setFailed] = useState(false);
  const load = () => {
    setFailed(false);
    api.setupCommand().then(setCmd, () => setFailed(true));
  };
  useEffect(() => {
    if (!given) load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return { cmd, failed, retry: load };
}

/** One line to paste into a terminal, shown whole (it wraps, never cut) with a
 *  Copy button. */
function CommandBox({ line }: { line: string }) {
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(null), 2500);
    return () => clearTimeout(t);
  }, [copied]);
  const copy = () => navigator.clipboard.writeText(line).then(() => setCopied("yes"), () => setCopied("no"));
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-start gap-2 border border-[var(--border)] bg-[var(--surface-2)] p-3">
        <code className="min-w-0 flex-1 select-all break-all font-mono text-sm">{line}</code>
        <Button onClick={() => void copy()}>{copied === "yes" ? "Copied" : "Copy"}</Button>
      </div>
      {copied === "no" && <Message tone="warning" text="Could not copy. Select the line and copy it." />}
    </div>
  );
}

/** Step 2's body; exported for the layout harness (harness.tsx), which passes
 *  `command` because it has no agent to ask. */
export function Install({ setup, run, busy, onClose, command }: {
  setup: SetupState | null; run: Run; busy: boolean; onClose: () => void; command?: SetupCommand;
}) {
  const phase = setup?.phase ?? "idle";
  const working = phase === "checking" || phase === "installing" || phase === "verifying";
  const settled = phase === "ready" || phase === "done";
  const battery = setup?.facts?.battery_v;
  const needsAny = setup ? Object.values(setup.parts).some((p) => p === "needed") : false;
  // Installed parts ticked to be written again. A tick belongs to the check it
  // was made against, so it clears whenever Set up moves on.
  const [again, setAgain] = useState<ReadonlySet<SetupPart>>(new Set());
  useEffect(() => {
    if (!settled) setAgain(new Set());
  }, [settled]);
  const tick = (part: SetupPart, on: boolean) => setAgain((prev) => {
    const next = new Set(prev);
    for (const p of DECK_PARTS.includes(part) ? DECK_PARTS : [part]) {
      if (on) next.add(p); else next.delete(p);
    }
    return next;
  });
  const { cmd, failed: cmdFailed, retry: cmdRetry } = useSetupCommand(command);
  // The order the agent lists parts in, so the line reads the same every time.
  const ticked = (setup?.order ?? []).filter((p) => again.has(p));
  const line = cmd && (ticked.length ? `${cmd.command} --reinstall ${ticked.join(",")}` : cmd.command);
  const showCommand = !working && ((phase === "ready" && needsAny) || (phase === "done" && again.size > 0));

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

      {phase === "ready" && setup?.facts?.deck_unrecorded && (
        <Message tone="warning"
                 text="This AI deck is not recorded on this drone — a new deck, or one set up before decks were recorded. The command below puts its camera and Wi-Fi software on it." />
      )}

      {setup && setup.order && Object.keys(setup.parts).length > 0 && (
        <ul className="grid border border-[var(--border)]">
          {setup.order.map((part) => {
            const status = setup.parts[part];
            const active = setup.current === part && phase === "installing";
            const canTick = settled && status === "installed";
            return (
              <li key={part} className="grid gap-1 border-b border-[var(--border)] px-3 py-2 last:border-b-0">
                <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
                  <span className="font-medium">{setup.labels[part]}</span>
                  <span className="flex flex-wrap items-center gap-3">
                    <PartStatus status={status} active={active} progress={setup.progress}
                                again={canTick && again.has(part)} />
                    {canTick && (
                      <label className="inline-flex min-h-11 items-center gap-2 text-xs">
                        <input type="checkbox" className="h-5 w-5" disabled={busy}
                               checked={again.has(part)} onChange={(e) => tick(part, e.target.checked)}
                               aria-label={`Reinstall ${setup.labels[part]}`} />
                        Reinstall
                      </label>
                    )}
                  </span>
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

      {showCommand && (
        <div className="grid gap-2">
          <p className="text-sm font-medium">Quit DroneDeck, then run this in Terminal:</p>
          {line ? <CommandBox line={line} />
            : cmdFailed ? (
              <div className="flex flex-wrap items-center gap-2">
                <Message tone="critical" text="Could not get the install command from the agent." />
                <Button onClick={cmdRetry}>Try again</Button>
              </div>
            ) : <Spinner label="Getting the command…" />}
          <p className="text-xs text-[var(--muted)]">
            About 5 minutes. Keep the drone on until it asks you to unplug the battery. Then open DroneDeck and check the drone.
          </p>
        </div>
      )}

      {!working && (
        <div className="flex flex-wrap items-center gap-2">
          {phase === "done" ? (
            <>
              <Button onClick={onClose}>Close</Button>
              {again.size === 0 && <span className="text-xs text-[var(--muted)]">Tick a part to write it again.</span>}
            </>
          ) : (
            <Button variant={showCommand ? "secondary" : "primary"} disabled={busy}
                    onClick={() => void run(api.setupCheck, "Check the drone")}>
              {phase === "failed" ? "Try again" : "Check the drone"}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** Each base station on its own channel, set over its USB cable. */
function Channels({ station, run, onDone }: {
  station: StationStatus | null; run: Run; onDone: () => void;
}) {
  const [found, setFound] = useState<BaseStation[] | null>(null);
  const [working, setWorking] = useState(false);
  const [outcome, setOutcome] = useState<{ tone: Tone; text: string } | null>(null);
  const scan = () => {
    setWorking(true);
    setOutcome(null);
    void run(async () => {
      try {
        setFound((await api.baseStations()).stations);
      } catch (e) {
        setOutcome({ tone: "critical", text: e instanceof AgentError ? e.message : "Could not look for base stations." });
        throw e;
      }
    }, "Look for base stations").finally(() => setWorking(false));
  };
  const setChannel = (port: string, channel: number) => {
    setWorking(true);
    void run(async () => {
      try {
        const r = await api.setBaseStationChannel(port, channel);
        setOutcome({ tone: "good", text: `Channel ${r.channel} set and saved. Unplug its USB cable, and do the other station.` });
        setFound((await api.baseStations()).stations);
      } catch (e) {
        setOutcome({ tone: "critical", text: e instanceof AgentError ? e.message : "The channel was not set." });
        throw e;
      }
    }, `Set base station channel ${channel}`).finally(() => setWorking(false));
  };
  const decoding = station?.connected === true && station.received.length > 0;
  return (
    <div className="grid gap-3">
      {station?.connected === true && <StationStages station={station} />}
      <ol className="grid gap-1 text-sm">
        <li>1. Keep the base station on its power block. Connect it to this laptop with a micro-USB cable — one station at a time.</li>
        <li>2. Press Look for base stations, then give the first station channel 1 and the second channel 2.</li>
        <li>3. Unplug the USB cables. The stations keep their channels.</li>
      </ol>
      {working && <Spinner label="Talking to the base station…" />}
      {outcome && !working && <Message tone={outcome.tone} text={outcome.text} />}
      {found !== null && found.length === 0 && !working && (
        <Message tone="warning" text="No base station on USB. Check the cable carries data (not only power) and the station is on." />
      )}
      {found !== null && found.length > 0 && (
        <ul className="grid border border-[var(--border)]">
          {found.map((s) => (
            <li key={s.port} className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2 text-sm last:border-b-0">
              <span>
                <span className="mono">{s.serial_number ?? s.port}</span>{" · "}
                <StatusDot tone={s.supported ? "good" : "warning"}>
                  {s.channel == null ? "did not answer" : s.channel === 0 ? "channel 0 — the drone cannot decode it" : `channel ${s.channel}`}
                </StatusDot>
              </span>
              <span className="flex gap-2">
                <Button disabled={working} onClick={() => setChannel(s.port, 1)}>Channel 1</Button>
                <Button disabled={working} onClick={() => setChannel(s.port, 2)}>Channel 2</Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={working} onClick={scan}>Look for base stations</Button>
        {decoding && <Button onClick={onDone}>Decoding — continue</Button>}
      </div>
    </div>
  );
}

function PartStatus({ status, active, progress, again }: {
  status: string | undefined; active: boolean; progress: number; again: boolean;
}) {
  const [tone, label]: [Tone, string] = active ? ["warning", `${Math.round(progress * 100)}%`]
    : again ? ["idle", "To reinstall"]
    : status === "installed" || status === "done" ? ["good", "Installed"]
    : status === "needed" ? ["idle", "To install"]
    : status === "absent" ? ["idle", "No deck fitted"] : ["idle", "—"];
  return <span className="text-xs"><StatusDot tone={tone}>{label}</StatusDot></span>;
}

function Item({ n, title, done, open, summary, children, onReopen, reopenLabel }: {
  n: number; title: string; done: boolean; open: boolean; summary: string; children: ReactNode;
  onReopen?: () => void; reopenLabel?: string;
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
        {!open && onReopen && <Button onClick={onReopen}>{reopenLabel ?? "Open"}</Button>}
      </div>
      {open && <div className="grid gap-3 border-t border-[var(--border)] px-4 py-3">{children}</div>}
    </li>
  );
}
