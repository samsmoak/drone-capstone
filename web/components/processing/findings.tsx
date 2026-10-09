import Image from "next/image";
import Link from "next/link";
import type { FindingRow } from "@/lib/queries";
import { StatusBadge } from "@/components/ui/states";
import { SEVERITY, clock, severityOf, unitSymbol } from "@/lib/pipeline";

/**
 * What the data pipeline found: each stretch of a flight whose temperature or
 * pressure departed from what was expected, judged and put into words by the
 * agent (stages/interpret/findings.py) — worst first.
 *
 * THE READINGS ARE THE EVIDENCE; the frames taken during the stretch are shown
 * beside them, original next to enhanced, because the camera may have been
 * facing away. The finding says whether an image model backs it ("cannot
 * tell" until one exists).
 */

/** Links to a frame: the original, and its enhanced copy when there is one. */
export type FrameLinks = Record<number, { original?: string; enhanced?: string }>;

/** How many frames each finding shows; the rest are counted. */
const SHOWN_FRAMES = 4;

function Change({ f }: { f: FindingRow }) {
  const unit = unitSymbol(f.unit);
  const digits = f.signal === "pressure" ? 2 : 1;
  if (f.observed === null || f.expected === null) return null;
  return (
    <>
      {f.observed.toFixed(digits)} {unit} measured against {f.expected.toFixed(digits)} {unit}{" "}
      expected — {f.delta !== null && f.delta > 0 ? "+" : ""}{f.delta?.toFixed(digits)} {unit}
      {f.z !== null ? (f.z >= 100 ? ", far beyond the flight's noise"
        : `, ${Math.round(f.z)}× the flight's noise`) : ""}
    </>
  );
}

function Where({ f }: { f: FindingRow }) {
  const points = f.point_ids.length ? f.point_ids.join(", ") : "Between inspection points";
  const place = f.x_m !== null && f.y_m !== null && f.z_m !== null
    ? ` · (${f.x_m.toFixed(2)}, ${f.y_m.toFixed(2)}) m, ${f.z_m.toFixed(2)} m up`
    : " · position not measured";
  return <>{points}{place}</>;
}

export function FindingCard({ f, frames, flight }: {
  f: FindingRow;
  frames: FrameLinks;
  /** On a session page: which flight it is from, and its page. */
  flight?: { label: string; href: string };
}) {
  const sev = SEVERITY[severityOf(f.severity)];
  const shown = f.evidence_frames.slice(0, SHOWN_FRAMES);
  return (
    <article id={`finding-${f.id}`}
             className="scroll-mt-24 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold">{f.title}</h3>
        <StatusBadge status={sev.status} label={sev.label} />
      </header>
      <p className="text-sm">{f.sentence}</p>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-[var(--muted)]">When</dt>
        <dd>
          {clock(f.t_start_s)}–{clock(f.t_end_s)} into the flight
          {flight && (
            <>
              {" · "}
              <Link href={`${flight.href}#finding-${f.id}`} className="underline underline-offset-4">
                {flight.label}
              </Link>
            </>
          )}
        </dd>
        <dt className="text-[var(--muted)]">Where</dt>
        <dd><Where f={f} /></dd>
        <dt className="text-[var(--muted)]">Change</dt>
        <dd><Change f={f} /></dd>
        <dt className="text-[var(--muted)]">Camera</dt>
        <dd>{f.image_note}</dd>
      </dl>
      {shown.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2" aria-label="Frames taken during this stretch">
          {shown.map((seq) => {
            const links = frames[seq] ?? {};
            return (
              <li key={seq} className="space-y-1">
                <div className="grid grid-cols-2 gap-1">
                  {(["original", "enhanced"] as const).map((which) => (
                    <div key={which} className="relative aspect-[4/3] overflow-hidden rounded-md bg-black">
                      {links[which] ? (
                        <Image src={links[which] as string} alt={`Frame ${seq}, ${which}`} fill unoptimized
                               sizes="(max-width: 640px) 50vw, 25vw" className="object-contain" />
                      ) : (
                        <span className="absolute inset-0 flex items-center justify-center p-2 text-center text-xs text-white">
                          {which === "original" ? "Not uploaded yet" : "No enhanced copy"}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <p className="text-xs">Frame {seq} · original · enhanced</p>
              </li>
            );
          })}
        </ul>
      )}
      {f.evidence_frames.length > SHOWN_FRAMES && (
        <p className="text-xs text-[var(--muted)]">
          And {f.evidence_frames.length - SHOWN_FRAMES} more frames from this stretch in the camera
          section below.
        </p>
      )}
    </article>
  );
}

export function FindingsList({ findings, frames, flightOf }: {
  findings: FindingRow[];
  frames: FrameLinks;
  flightOf?: (flightId: string) => { label: string; href: string } | undefined;
}) {
  return (
    <div className="space-y-3">
      {findings.map((f) => (
        <FindingCard key={f.id} f={f} frames={frames} flight={flightOf?.(f.flight_id)} />
      ))}
    </div>
  );
}
