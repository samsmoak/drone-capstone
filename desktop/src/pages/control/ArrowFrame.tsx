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
 * WITHOUT A POSITION (no base stations) "From you" and "Room" cannot work —
 * nothing knows where the drone or you are — so they give way to NOSE POINTS:
 * where the nose points as you stand. The drone can be set down any way round;
 * ↑ is then away from you as you stood at takeoff, kept by its heading however
 * it turns (keyframe.py). Changeable in the air, and still counted from
 * takeoff there, which the buttons' titles say. SHIFT + AN ARROW does the same
 * from the keyboard (App.tsx ALIGN_KEYS): the nose on the ground, and in the
 * air which way ↑ just went — the correction for turning round.
 *
 * SPEED, Slow or Normal, is how fast the KEYS fly it (flight/manual.py SPEEDS);
 * a mission and "Hover at" keep their own. Changeable in the air — every
 * command eases to it, so there is no jolt.
 */

import type { Run } from "@/App";
import { api, type KeySpeed, type Session } from "@/lib/agent";
import { arrowWords, NOSE_CHOICES } from "@/lib/arrows";
import { SmallButton } from "./auto/plan/fields";

const SPEED_CHOICES: { value: KeySpeed; label: string; title: string }[] = [
  { value: "slow", label: "Slow",
    title: "Gentler keys, steadier flight: a smaller lean, slower turns and climbs" },
  { value: "normal", label: "Normal",
    title: "The keys at full speed, as before" },
];

export function ArrowFrame({ session, run }: { session: Session; run: Run }) {
  const controls = session.controls;
  const words = arrowWords(controls, session.assisted);
  const connected = session.radio.state === "connected" || session.state === "ready" || session.state === "busy";
  const canMark = connected && session.assisted;
  const marked = controls.operator;
  // No position: the nose choice is what makes "away from you". Also while an
  // assisted flight waits for its first position (the agent says "takeoff").
  const noPosition = !session.assisted || controls.live?.active === "takeoff";
  const inAir = controls.live !== null;

  return (
    <div className="grid gap-1.5 border-t border-[var(--border)] pt-2.5">
      {noPosition && (
        <div className="flex flex-wrap items-center gap-1.5">
          <p className="eyebrow pr-1">{inAir ? "Nose at takeoff" : "Nose points"}</p>
          <div className="flex gap-1" role="group" aria-label="Where the drone's nose points, as you stand">
            {NOSE_CHOICES.map((choice) => (
              <SmallButton key={choice.value} pressed={controls.nose === choice.value}
                           onClick={() => void run(() => api.setNose(choice.value), `Nose ${choice.where}`)}
                           title={inAir
                             ? `At takeoff its nose pointed ${choice.where}: ↑ flies away from where you stood then`
                             : `Its nose points ${choice.where}: ↑ flies away from you, however it turns after takeoff`}>
                {choice.label}
              </SmallButton>
            ))}
          </div>
        </div>
      )}
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
      <div className="flex flex-wrap items-center gap-1.5">
        <p className="eyebrow pr-1">Speed</p>
        <div className="flex gap-1" role="group" aria-label="How fast the keys fly the drone">
          {SPEED_CHOICES.map((choice) => (
            <SmallButton key={choice.value} pressed={controls.speed === choice.value}
                         onClick={() => void run(() => api.setSpeed(choice.value), `Speed ${choice.value}`)}
                         title={choice.title}>
              {choice.label}
            </SmallButton>
          ))}
        </div>
      </div>
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
