"use client";

import Link from "next/link";
import { timeAgo } from "./useDraft";
import { Button } from "./ui";

/**
 * The bar every admin editor wears: where you are, what state the work is in,
 * and Save — pinned to the top so it is reachable without scrolling back.
 *
 * PARITY: extracted from components/admin/PageEditor.tsx, which was the only
 * editor with a sticky header. The other five (ProjectEditor, AlbumEditor,
 * TeamManager, ProjectsManager, AlbumsManager) scrolled their Save button off
 * the screen, so a long page had to be scrolled to the top to save it.
 *
 * `max-lg:top-[6.5rem]` clears the operator shell's mobile bar, which is
 * sticky itself; on a wide screen the sidebar is fixed and the bar sits at 0.
 */

export type EditorState =
  | { kind: "idle" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved"; text?: string }
  | { kind: "error"; text: string };

export function EditorBar({
  back,
  backLabel,
  title,
  description,
  state,
  children,
}: {
  back?: string;
  backLabel?: string;
  title: string;
  description?: string;
  state: EditorState;
  /** The actions: View, Reset, Save — in that order, Save last. */
  children: React.ReactNode;
}) {
  return (
    <header className="sticky top-0 z-20 -mx-2 flex max-lg:top-[6.5rem] flex-wrap items-center justify-between gap-4 rounded-b-xl bg-[var(--background)]/95 px-2 py-3 backdrop-blur">
      <div className="min-w-0">
        {back && (
          <Link href={back} className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]">
            ← {backLabel}
          </Link>
        )}
        <h1 className="font-display mt-1 text-3xl font-semibold">{title}</h1>
        {description && <p className="text-sm text-[var(--muted)]">{description}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <EditorStatus state={state} />
        {children}
      </div>
    </header>
  );
}

function EditorStatus({ state }: { state: EditorState }) {
  switch (state.kind) {
    case "error":
      // role=alert: a failed save must reach a screen reader without the
      // operator having to go looking for it.
      return (
        <span role="alert" className="max-w-md text-sm font-medium text-[var(--status-critical)]">
          {state.text}
        </span>
      );
    case "saved":
      return (
        <span role="status" className="text-sm font-medium">
          {state.text ?? "Saved ✓"}
        </span>
      );
    case "saving":
      return <span role="status" className="text-sm text-[var(--muted)]">Saving…</span>;
    case "dirty":
      return <span className="text-sm text-[var(--muted)]">Unsaved changes</span>;
    default:
      return null;
  }
}

/**
 * The offer to put back what was typed before the page went away. Shown rather
 * than restored silently: a draft that overwrites the saved version without
 * asking is its own kind of data loss.
 */
export function DraftNotice({
  savedAt,
  onRestore,
  onDiscard,
}: {
  savedAt: number;
  onRestore: () => void;
  onDiscard: () => void;
}) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--status-warning)] bg-[var(--surface)] p-4"
    >
      <p className="text-sm">
        <strong>You have unsaved changes</strong> in this browser from {timeAgo(savedAt)}. They
        were never saved — the page closed, or an error interrupted it.
      </p>
      <div className="flex gap-2">
        <Button onClick={onRestore}>Put them back</Button>
        <Button variant="ghost" onClick={onDiscard}>Discard them</Button>
      </div>
    </div>
  );
}
