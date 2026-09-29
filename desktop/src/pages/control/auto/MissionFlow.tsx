/**
 * The Auto flow: ① Mission → ② Check → ③ Fly.
 *
 * Adapted from the Zoomaa booking flow (booking_flow_screen.dart): one screen,
 * a step bar across the top, back always allowed, forward only once the step
 * before is satisfied — and here "satisfied" is read from the agent, never
 * decided by the page:
 *
 *   ① Mission  done when a mission is chosen that the agent says is valid
 *   ② Check    done when the agent reports ready (checks passed, area confirmed,
 *              no retry owed)
 *   ③ Fly      Start mission at the top; LOCKED here while a mission flies, so
 *              no plan can be changed in the air
 *
 * The chosen mission is remembered per machine (localStorage), a convenience
 * only: the agent re-reads and re-validates the mission when it is started.
 */

import { useEffect, useState } from "react";
import type { History, Run } from "@/App";
import { api, type MissionView, type Session, type Telemetry } from "@/lib/agent";
import { CheckStep, checkComplete } from "./CheckStep";
import { FlyStep } from "./FlyStep";
import { MissionStep } from "./plan/MissionStep";
import { StepBar, type FlowStep, type StepState } from "./StepBar";

const CHOSEN_KEY = "cropwatcher.auto.mission";

function remembered(): string | null {
  try { return localStorage.getItem(CHOSEN_KEY); } catch { return null; }
}

function remember(id: string | null): void {
  try {
    if (id) localStorage.setItem(CHOSEN_KEY, id);
    else localStorage.removeItem(CHOSEN_KEY);
  } catch { /* a private window: the choice lasts until the window closes */ }
}

/** Where the flow opens. The app never sets it (it opens on ①, or ③ while a
 *  mission flies); the layout harness does, to measure every step. */
export type FlowStart = { step?: FlowStep; missionId?: string; view?: "edit"; full?: boolean };

export function MissionFlow({ session, run, telemetry, history, ambient, setAmbient, start, full = false, onFullScreen, heightClass }: {
  /** Whether the flow is filling the window (AutoControl's FullScreenFrame). */
  full?: boolean;
  onFullScreen?: () => void;
  /** The room maps' height — taller in full screen. */
  heightClass?: string;
  session: Session;
  run: Run;
  telemetry: Telemetry | null;
  history: History;
  ambient: string;
  setAmbient: (value: string) => void;
  start?: FlowStart;
}) {
  const flying = session.activity === "mission";
  const [chosen, setChosen] = useState<MissionView | null>(null);
  const [step, setStep] = useState<FlowStep>(flying ? 3 : start?.step ?? 1);

  // Reopen on the mission chosen last time, if it is still here.
  useEffect(() => {
    const id = session.mission?.id ?? start?.missionId ?? remembered();
    if (!id || chosen) return;
    api.mission(id).then(setChosen).catch(() => remember(null));
  }, [session.mission?.id, start?.missionId, chosen]);

  // A mission in the air pins the flow to Fly.
  useEffect(() => { if (flying) setStep(3); }, [flying]);

  const choose = (mission: MissionView) => {
    setChosen(mission);
    remember(mission.id);
    setStep(2);
  };

  const ready = checkComplete(session);
  const steps: StepState[] = [
    { step: 1, label: "Mission", done: chosen?.valid ?? false,
      blocked: flying ? "A mission is flying — the plan cannot change in the air." : null },
    { step: 2, label: "Check", done: ready,
      blocked: flying ? "A mission is flying."
        : !chosen ? "Choose a mission first."
        : !chosen.valid ? "The chosen mission has problems to fix." : null },
    { step: 3, label: "Fly", done: false,
      blocked: flying ? null
        : !chosen ? "Choose a mission first."
        : !ready ? "Pass the checks and confirm the area first." : null },
  ];

  return (
    <section aria-label="Mission" className="grid content-start gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1"><StepBar steps={steps} current={step} onSelect={setStep} /></div>
        {!full && onFullScreen && (
          <button type="button" onClick={onFullScreen} title="Plan with the whole window"
                  className="mono min-h-9 shrink-0 border border-[var(--border)] px-2.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]">
            Full screen ⤢
          </button>
        )}
      </div>

      {step === 1 && (
        <MissionStep run={run} telemetry={telemetry} selectedId={chosen?.id ?? null} onUse={choose}
                     openEditor={start?.view === "edit" ? start.missionId : undefined} heightClass={heightClass} />
      )}
      {step === 2 && (
        <CheckStep session={session} run={run} mission={chosen} onContinue={() => setStep(3)} />
      )}
      {step === 3 && chosen && (
        <FlyStep session={session} run={run} telemetry={telemetry} history={history} mission={chosen}
                 ambient={ambient} setAmbient={setAmbient} onPlanAnother={() => setStep(1)} heightClass={heightClass} />
      )}
    </section>
  );
}
