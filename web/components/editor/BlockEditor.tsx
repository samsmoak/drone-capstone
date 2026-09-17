"use client";

import { useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/core/fonts/inter.css";
import "@blocknote/mantine/style.css";
import type { Block } from "@blocknote/core";
import { useSyncExternalStore } from "react";
import { uploadFileForEditor } from "@/lib/upload";
import type { Json } from "@/types/database";

/**
 * The write-up editor. Copied from ../doctor-portfolio. That site has a theme
 * toggle; this one follows the system, so the editor reads the same media query
 * the tokens do.
 */
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
  const editor = useCreateBlockNote({
    initialContent:
      Array.isArray(initialContent) && initialContent.length > 0
        ? (initialContent as unknown as Block[])
        : undefined,
    uploadFile: uploadFileForEditor,
  });

  return (
    <div className="portfolio-editor">
      <BlockNoteView
        editor={editor}
        theme={theme}
        onChange={() => onChange(editor.document as unknown as Json)}
      />
    </div>
  );
}
