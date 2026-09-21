"use client";

import { useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/core/fonts/inter.css";
import "@blocknote/mantine/style.css";
import type { Block } from "@blocknote/core";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { uploadFileForEditor } from "@/lib/upload";
import type { Json } from "@/types/database";

/**
 * The write-up editor. Copied from ../doctor-portfolio. That site has a theme
 * toggle; this one follows the system, so the editor reads the same media query
 * the tokens do.
 *
 * PASTED IMAGES ARE UPLOADED, NOT EMBEDDED. Dragging a file in has always gone
 * through uploadFile; pasting from a word processor does not — the image
 * arrives in the clipboard as a data: URI and BlockNote keeps it inline. A
 * Google Docs page pasted whole then weighs megabytes, and Server Actions are
 * capped at 1 MB by default, so the save was rejected before it reached the
 * database (2026-09-21: "This page couldn't load", and the writing was gone).
 *
 * So every data: image is uploaded as it appears and the block is pointed at
 * the stored copy. The document stays small, and the images survive — the
 * clipboard copy would have been lost the moment the page closed anyway.
 */

/** Blocks whose image is still sitting in the document as base64. */
function embeddedImages(blocks: Block[]): { id: string; url: string }[] {
  const found: { id: string; url: string }[] = [];
  const walk = (list: Block[]) => {
    for (const block of list) {
      const url = (block.props as { url?: string } | undefined)?.url;
      if (typeof url === "string" && url.startsWith("data:")) found.push({ id: block.id, url });
      if (block.children?.length) walk(block.children as Block[]);
    }
  };
  walk(blocks);
  return found;
}

async function asFile(dataUrl: string, name: string): Promise<File> {
  const blob = await (await fetch(dataUrl)).blob();
  const extension = (blob.type.split("/")[1] ?? "png").replace("+xml", "");
  return new File([blob], `${name}.${extension}`, { type: blob.type });
}
function useSystemTheme(): "light" | "dark" {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia("(prefers-color-scheme: dark)");
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
    () => "light",
  );
}

export default function BlockEditor({
  initialContent,
  onChange,
}: {
  initialContent: Json;
  onChange: (document: Json) => void;
}) {
  const theme = useSystemTheme();
  const [uploading, setUploading] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const busy = useRef(new Set<string>());
  const editor = useCreateBlockNote({
    initialContent:
      Array.isArray(initialContent) && initialContent.length > 0
        ? (initialContent as unknown as Block[])
        : undefined,
    uploadFile: uploadFileForEditor,
  });

  const lift = useCallback(async () => {
    const pending = embeddedImages(editor.document as Block[]).filter((b) => !busy.current.has(b.id));
    if (pending.length === 0) return;
    for (const { id, url } of pending) {
      busy.current.add(id);
      setUploading((n) => n + 1);
      try {
        const stored = await uploadFileForEditor(await asFile(url, `pasted-${Date.now()}`));
        editor.updateBlock(id, { props: { url: stored } } as never);
        setFailed(null);
      } catch (error) {
        // Left inline rather than dropped: the operator can still see their
        // image, and the save guard below explains why it will not go through.
        setFailed(error instanceof Error ? error.message : "That image could not be uploaded.");
      } finally {
        busy.current.delete(id);
        setUploading((n) => n - 1);
      }
    }
    onChange(editor.document as unknown as Json);
  }, [editor, onChange]);

  // Catch anything already in the document from before this existed. On a
  // timer rather than in the effect body: uploading sets state, and doing that
  // synchronously inside an effect cascades renders.
  useEffect(() => {
    const timer = setTimeout(() => { void lift(); }, 0);
    return () => clearTimeout(timer);
  }, [lift]);

  return (
    <div className="portfolio-editor">
      {uploading > 0 && (
        <p role="status" className="mb-2 text-sm text-[var(--muted)]">
          Uploading {uploading} pasted image{uploading === 1 ? "" : "s"}… they are stored on the
          site rather than kept inside the write-up.
        </p>
      )}
      {failed && (
        <p role="alert" className="mb-2 text-sm text-[var(--status-critical)]">
          A pasted image could not be uploaded: {failed} Remove it, or add it again with the
          image button, before saving.
        </p>
      )}
      <BlockNoteView
        editor={editor}
        theme={theme}
        onChange={() => {
          onChange(editor.document as unknown as Json);
          void lift();
        }}
      />
    </div>
  );
}
