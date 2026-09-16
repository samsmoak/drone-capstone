import Link from "next/link";
import { AgentStatus } from "@/components/ui/agent-status";
import { DownloadButtons } from "@/components/ui/download-buttons";
import { HARDWARE } from "@/lib/routes";

export const metadata = {
  title: "Set up the system",
  description:
    "Get CropWatcher flying: what you need, installing the app, positioning " +
    "setup, your first flight, and what to do when it will not take off.",
};

const STEPS = [
  {
    n: 1,
    title: "Check you have everything",
    body: (
      <>
        <p className="text-[var(--muted)]">
          Six things. Miss one and the drone either will not fly or will not know
          where it is.
        </p>
        <ul className="mt-3 space-y-1.5 text-sm">
          {[
            "Crazyflie 2.1 drone, assembled with propellers fitted",
            "Lighthouse positioning deck — a small board with four black domes",
            "Two Lighthouse V2 base stations",
            "Crazyradio PA — the USB dongle with the antenna",
            "At least one charged LiPo battery",
            "A USB-C to micro-USB cable, for charging",
          ].map((item) => (
            <li key={item} className="flex gap-2">
              <span aria-hidden="true" className="text-[var(--muted)]">
                •
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-[var(--muted)]">
          Not sure which part is which?{" "}
          <Link href={HARDWARE} className="underline underline-offset-4">
            See every component photographed and labelled
          </Link>
          .
        </p>
      </>
    ),
  },
  {
    n: 2,
    title: "Install the CropWatcher app",
    body: (
      <>
        <p className="text-[var(--muted)]">
          One download. It contains everything — you will not need Python, a
          terminal, or any commands.
        </p>
        <DownloadButtons />
        <p className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm">
          <strong>On a Mac</strong>, the first launch will say the app is from an
          unidentified developer. That is expected. Right-click the app and choose{" "}
          <em>Open</em>, then confirm. You only do this once.
        </p>
      </>
    ),
  },
  {
    n: 3,
    title: "Plug in the radio",
    body: (
      <p className="text-[var(--muted)]">
        The Crazyradio goes into your laptop, not the drone. It is a USB-A plug,
        so most modern Macs need a USB-C adapter or a hub. No driver to install —
        the app finds it.
      </p>
    ),
  },
  {
    n: 4,
    title: "Set up positioning",
    body: (
      <>
        <p className="text-[var(--muted)]">
          The drone cannot hold a position without this. Two base stations, in
          opposite corners of the flight area, about two metres up, both angled
          toward the middle.
        </p>
        <p className="mt-3 text-[var(--muted)]">
          Then run geometry calibration once: place the drone where you want the
          origin, keep it still, and start the estimate. Repeat this any time a
          base station is moved or knocked.
        </p>
      </>
    ),
  },
  {
    n: 5,
    title: "Check before you fly",
    body: (
      <>
        <p className="text-[var(--muted)]">
          Press <strong>Check</strong> in the app. Nothing spins — it asks the
          drone four questions and shows the answers:
        </p>
        <ul className="mt-3 space-y-1.5 text-sm text-[var(--muted)]">
          <li>Is the battery charged enough to arm?</li>
          <li>Is the positioning deck fitted?</li>
          <li>Can it see the base stations?</li>
          <li>Has its position estimate settled?</li>
        </ul>
        <p className="mt-3 text-sm">
          All four green means you are ready. Anything else tells you exactly
          what to fix.
        </p>
      </>
    ),
  },
  {
    n: 6,
    title: "Your first flight",
    body: (
      <>
        <p className="text-[var(--muted)]">
          Start small: 30 cm for a few seconds. Put the drone on the{" "}
          <strong>floor</strong>, not a table, with about two metres clear around
          it and nothing fragile nearby.
        </p>
        <p className="mt-3 text-[var(--muted)]">
          It will take off, hold its height, and land by itself. Once that works,
          scale up.
        </p>
      </>
    ),
  },
];

const TROUBLESHOOTING = [
  {
    symptom: "I press fly and absolutely nothing happens",
    cause: "The battery is too low for the drone to arm.",
    fix:
      "The drone refuses to spin its motors below about 3.75 V, and it will not " +
      "tell you out loud. Charge for 20–30 minutes, then power-cycle the drone. " +
      "The Check screen shows this as 'firmware will not arm'.",
  },
  {
    symptom: "The app says no drone found",
    cause: "The radio or the drone is not visible.",
    fix:
      "Confirm the dongle is plugged in — with an adapter if your laptop is " +
      "USB-C only. Then confirm the battery is connected and the drone is " +
      "switched on. LEDs lighting up does not mean the battery is charged.",
  },
  {
    symptom: "It lifts a few centimetres and will not go higher",
    cause: "It has no position feedback, so it cannot climb safely.",
    fix:
      "Check the Lighthouse deck is fitted and both base stations are powered " +
      "and visible. If the Check screen shows zero base stations, something is " +
      "blocking the line of sight.",
  },
  {
    symptom: "It drifts around instead of holding still",
    cause: "The position estimate is unstable where the drone is sitting.",
    fix:
      "Move it back toward the middle of the flight area and try again. If it " +
      "keeps drifting, re-run geometry calibration — a base station has probably " +
      "been moved.",
  },
  {
    symptom: "It flew, then landed on its own part-way through",
    cause: "The battery dropped to the safety threshold.",
    fix:
      "This is the system working. It lands under control rather than cutting " +
      "out mid-air. Charge fully before a long mission — a full pack gives " +
      "roughly four minutes of flight.",
  },
  {
    symptom: "Manual control will not connect",
    cause: "The browser cannot reach the app on your machine.",
    fix:
      "Manual flight needs the CropWatcher app running on the same computer or " +
      "the same network. It deliberately does not work over the internet: the " +
      "delay would make the drone unflyable.",
  },
];

export default function SetupPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-14">
      <h1 className="text-3xl font-semibold tracking-tight">Set up the system</h1>
      <p className="mt-3 text-lg text-[var(--muted)]">
        From an unopened box to a first flight. About 30 minutes, most of it
        waiting for a battery.
      </p>

      <div className="mt-8">
        <AgentStatus />
      </div>

      <ol className="mt-12 space-y-10">
        {STEPS.map((step) => (
          <li key={step.n} className="flex gap-5">
            <span
              aria-hidden="true"
              className="tabular flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-sm font-semibold"
            >
              {step.n}
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-medium">{step.title}</h2>
              <div className="mt-2">{step.body}</div>
            </div>
          </li>
        ))}
      </ol>

      <section className="mt-16 border-t border-[var(--border)] pt-10">
        <h2 className="text-2xl font-semibold tracking-tight">
          When it will not fly
        </h2>
        <p className="mt-2 text-[var(--muted)]">
          Every one of these cost us real time during bring-up. Symptoms first,
          because that is what you actually see.
        </p>

        <div className="mt-6 space-y-4">
          {TROUBLESHOOTING.map((item) => (
            <details
              key={item.symptom}
              className="group rounded-lg border border-[var(--border)] bg-[var(--surface)]"
            >
              <summary className="flex min-h-11 cursor-pointer items-center px-4 py-3 font-medium">
                {item.symptom}
              </summary>
              <div className="border-t border-[var(--border)] px-4 py-3">
                <p className="text-sm">
                  <span className="text-[var(--muted)]">Usually: </span>
                  {item.cause}
                </p>
                <p className="mt-2 text-sm text-[var(--muted)]">{item.fix}</p>
              </div>
            </details>
          ))}
        </div>
      </section>
    </main>
  );
}
