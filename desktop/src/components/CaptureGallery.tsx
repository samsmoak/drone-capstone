/**
 * A session's frames captured by hand, as a gallery — on the Capture page
 * while the session runs, and in Sessions once it has ended (2026-10-24,
 * Samuel: "the manually captured images get displayed" where they are taken,
 * and labelled as manual captures of that session).
 *
 * Each image is fetched once, from this laptop's disk, through whichever
 * reader the caller gives (the running recording, or an ended session's
 * files), and kept as an object URL until the gallery goes away. Choosing one
 * shows it large; Close returns to the grid.
 */

import { useEffect, useRef, useState } from "react";
import type { RecordedFrameInfo } from "@/lib/agent";
import { formatTime } from "@/lib/format";
import { Button, Message, Spinner } from "@/components/ui";

export type GalleryLoad =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; frames: RecordedFrameInfo[] };

/** Seconds as m:ss, for a capture's place in its session. */
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function CaptureGallery({ load, read, onRetry, emptyText }: {
  load: GalleryLoad;
  /** One frame's image, by number. */
  read: (seq: number) => Promise<Blob | null>;
  onRetry: () => void;
  emptyText: string;
}) {
  const [urls, setUrls] = useState<Record<number, string | null>>({});
  const [open, setOpen] = useState<number | null>(null);
  const asked = useRef(new Set<number>());
  const all = useRef<string[]>([]);

  const frames = load.kind === "ready" ? load.frames : [];

  useEffect(() => {
    for (const f of frames) {
      if (asked.current.has(f.seq)) continue;
      asked.current.add(f.seq);
      void read(f.seq)
        .then((blob) => {
          const url = blob ? URL.createObjectURL(blob) : null;
          if (url) all.current.push(url);
          setUrls((u) => ({ ...u, [f.seq]: url }));
        })
        .catch(() => setUrls((u) => ({ ...u, [f.seq]: null })));
    }
  }, [frames, read]);

  // Release every image when the gallery goes away.
  useEffect(() => () => { all.current.forEach((u) => URL.revokeObjectURL(u)); }, []);

  if (load.kind === "loading") return <Spinner label="Loading the captures…" />;
  if (load.kind === "error") {
    return (
      <div className="grid gap-2">
        <Message tone="critical" text={load.message} />
        <div><Button onClick={onRetry}>Try again</Button></div>
      </div>
    );
  }
  if (frames.length === 0) return <p className="text-sm text-[var(--muted)]">{emptyText}</p>;

  const newestFirst = [...frames].reverse();
  const shown = open !== null ? frames.find((f) => f.seq === open) ?? null : null;

  return (
    <div className="grid gap-3">
      {shown && (
        <figure className="grid gap-2">
          {urls[shown.seq]
            ? <img src={urls[shown.seq] ?? ""} alt={`Captured manually at ${clock(shown.t_s)} — frame ${shown.seq}`}
                   className="max-h-[60vh] w-full border border-[var(--border)] bg-[var(--console)] object-contain" />
            : <p className="text-sm text-[var(--muted)]">This image could not be read from this computer.</p>}
          <figcaption className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="mono">
              Captured manually · {clock(shown.t_s)} into the session · {formatTime(shown.recorded_at)}
              {shown.point_id ? ` · at ${shown.point_id}` : ""} · frame {shown.seq}
            </span>
            <Button onClick={() => setOpen(null)}>Close</Button>
          </figcaption>
        </figure>
      )}
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2" aria-label="Captured manually, newest first">
        {newestFirst.map((f) => (
          <li key={f.seq}>
            <button
              type="button"
              onClick={() => setOpen(f.seq)}
              aria-pressed={open === f.seq}
              aria-label={`Captured manually at ${clock(f.t_s)}, frame ${f.seq}`}
              className={`grid w-full gap-1 border bg-[var(--surface)] p-1 text-left ${open === f.seq ? "border-[var(--primary)]" : "border-[var(--border)]"}`}
            >
              <span className="flex aspect-[4/3] items-center justify-center bg-[var(--console)]">
                {urls[f.seq] === undefined
                  ? <span className="text-xs text-[var(--console-dim)]">Loading…</span>
                  : urls[f.seq] === null
                    ? <span className="text-xs text-[var(--console-dim)]">Not on this computer</span>
                    : <img src={urls[f.seq] ?? ""} alt="" className="h-full w-full object-contain" />}
              </span>
              <span className="mono px-1 text-xs">{clock(f.t_s)} · #{f.seq}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
