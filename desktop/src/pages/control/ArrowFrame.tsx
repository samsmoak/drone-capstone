/**
 * Which way the arrow keys move the drone — chosen here, said here.
 *
 * Sits in the FlightDeck under the keys, so it is on screen whenever the keys
 * are: the frame can be switched in the air, and what the arrows mean right
 * now (a fallback near you, or with no position) is read with the same glance
 * as the keys themselves. The words come from lib/arrows.ts; the decision is
 * the agent's (cropwatcher/flight/keyframe.py).
 *
 * I'M HERE takes the DRONE's position as yours: carry it to your feet, or fly
 * it over your head, and press it. Without a mark, "away" is measured from
 * where the drone took off — ArduPilot's home — which is right whenever you
 * stand by the takeoff spot.
 *
 * WITHOUT A POSITION (no base stations) "From you" and "Room" cannot work, so
 * the row is only the sentence: ↑ flies the way the nose pointed at takeoff,
 * and holding Shift reverses the arrows (lib/keys.ts). No buttons for it —
 * the 2026-09-30 Nose and Speed buttons were taken out at the owner's word.
 */

import type { Run } from "@/App";
import { api, type Session } from "@/lib/agent";
import { arrowWords } from "@/lib/arrows";
import { SmallButton } from "./auto/plan/fields";

export function ArrowFrame({ session, run }: { session: Session; run: Run }) {
  const controls = session.controls;
  const words = arrowWords(controls, session.assisted);
  const connected = session.radio.state === "connected" || session.state === "ready" || session.state === "busy";
  const canMark = connected && session.assisted;
  const marked = controls.operator;
  return (
    <div className="grid gap-1.5 border-t border-[var(--border)] pt-2.5">
      {session.assisted && (
      <div className="flex flex-wrap items-center gap-1.5">
        <p className="eyebrow pr-1">Arrows</p>
        <div className="flex gap-1" role="group" aria-label="Arrow keys move the drone">
          <SmallButton pressed={controls.key_frame === "operator"}
                       onClick={() => void run(() => api.setKeyFrame("operator"), "Arrows from you")}
                       title="↑ flies it away from you, ↓ back, ← → round you — whichever way its nose points">
            From you
          </SmallButton>
          <SmallButton pressed={controls.key_frame === "room"}
                       onClick={() => void run(() => api.setKeyFrame("room"), "Arrows in room directions")}
                       title="↑ is the room's forward, set with the base stations — whichever way its nose points">
            Room
          </SmallButton>
        </div>
        {controls.key_frame === "operator" && (
          <SmallButton onClick={() => void run(api.markOperatorHere, "I'm here")}
                       disabled={!canMark}
                       title={canMark
                         ? "Use the drone's position now as where you stand: carry it to your feet, or fly it over your head"
                         : session.assisted
                           ? "Connect the drone first: its position is what marks your spot"
                           : "Without base stations the drone has no position to mark"}>
            I'm here
          </SmallButton>
        )}
        {controls.key_frame === "operator" && marked && (
          <SmallButton onClick={() => void run(api.clearOperator, "Forget my spot")}
                       title="Measure “away” from where it takes off instead">
            Use takeoff spot
          </SmallButton>
        )}
      </div>
      )}
      <p role="status" className={`text-xs leading-snug ${words.warn ? "text-[var(--foreground)]" : "text-[var(--muted)]"}`}>
        {words.warn && <span aria-hidden className="mr-1 text-[var(--status-warning)]">▲</span>}
        {words.line}
        {controls.key_frame === "operator" && marked && !controls.live && (
          <span className="mono"> Your spot: ({marked[0].toFixed(2)}, {marked[1].toFixed(2)}) m.</span>
        )}
      </p>
    </div>
  );
}
