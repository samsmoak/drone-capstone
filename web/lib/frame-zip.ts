/**
 * A session's chosen camera frames, downloaded as one zip — in the browser.
 *
 * The frames sit in a private bucket behind signed links the page already
 * holds (lib/queries.ts getSessionFrames), so the browser fetches them itself:
 * nothing new is exposed and no server route has to stream a session's worth
 * of images (2026-10-24, Samuel: "click to either select all and download it,
 * or select the few that we wanted").
 *
 * Images are STORED, not compressed again — PNG and JPEG are compressed
 * already, and deflating them costs time for nothing. An index.csv beside them
 * says when and where each was taken, and whether it was captured by hand.
 */

import { Zip, ZipPassThrough, strToU8 } from "fflate";
import type { SessionFrame } from "@/lib/queries";

/** Fetched at once. Enough to keep the link busy, few enough not to choke it. */
const PARALLEL = 6;

export type ZipProgress = { done: number; total: number; failed: number };

export type ZipResult = {
  blob: Blob;
  /** Frames whose image could not be fetched — usually an expired link. */
  failed: SessionFrame[];
};

const cell = (v: number | string | null) => (v === null ? "" : String(v));

function timeTag(t: number | null): string {
  if (t === null || !Number.isFinite(t)) return "";
  const s = Math.floor(t);
  return `_${String(Math.floor(s / 60)).padStart(2, "0")}m${String(s % 60).padStart(2, "0")}s`;
}

/** The file's name inside the zip: its number, its time, and "manual". */
export function zipName(f: SessionFrame): string {
  const ext = f.name.split(".").pop() ?? "png";
  return `frame-${String(f.seq).padStart(6, "0")}${timeTag(f.t_s)}${f.source === "manual" ? "_manual" : ""}.${ext}`;
}

export async function zipFrames(
  frames: SessionFrame[],
  onProgress: (p: ZipProgress) => void,
  signal: AbortSignal,
): Promise<ZipResult> {
  const parts: Uint8Array[] = [];
  let error: Error | null = null;
  const zip = new Zip((err, chunk) => {
    if (err) error = err;
    else parts.push(chunk);
  });
  const failed: SessionFrame[] = [];
  let done = 0;

  const add = (name: string, data: Uint8Array) => {
    const entry = new ZipPassThrough(name);
    zip.add(entry);
    entry.push(data, true);
  };

  // In order of the list, PARALLEL at a time; each file is added as it lands.
  let next = 0;
  const worker = async () => {
    while (next < frames.length) {
      if (signal.aborted) return;
      const f = frames[next++];
      try {
        const response = await fetch(f.url, { signal });
        if (!response.ok) throw new Error(String(response.status));
        add(zipName(f), new Uint8Array(await response.arrayBuffer()));
      } catch {
        if (signal.aborted) return;
        failed.push(f);
      }
      done += 1;
      onProgress({ done, total: frames.length, failed: failed.length });
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, frames.length) }, worker));
  if (signal.aborted) throw new DOMException("Cancelled", "AbortError");

  const missing = new Set(failed.map((f) => f.seq));
  const rows = [
    "seq,file,t_s,x_m,y_m,z_m,source,point_id",
    ...frames.filter((f) => !missing.has(f.seq)).map((f) =>
      [f.seq, zipName(f), cell(f.t_s), cell(f.x_m), cell(f.y_m), cell(f.z_m), f.source, cell(f.point_id)].join(",")),
  ];
  add("index.csv", strToU8(rows.join("\n") + "\n"));
  zip.end();
  if (error) throw error;
  return { blob: new Blob(parts as BlobPart[], { type: "application/zip" }), failed };
}

/** Hand a blob to the browser as a download. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // The download has its own reference by now; give it a moment regardless.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
