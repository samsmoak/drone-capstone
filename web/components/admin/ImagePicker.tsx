"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import { uploadImage, type UploadPrefix } from "@/lib/upload";
import { Label } from "./ui";

/**
 * Upload or replace one image. Copied from ../doctor-portfolio.
 *
 * THREE WAYS IN, because people have three habits: the Upload button, dropping
 * a file on the frame, and pasting. Paste is the one that was missing and the
 * one people reach for first after copying out of a document or a browser —
 * the clipboard already holds the image, and being told to save it to disk
 * first is busywork.
 *
 * The frame is focusable so a paste has somewhere to land: a paste event goes
 * to whatever is focused, and a div is not focusable by default.
 */
export function ImagePicker({
  label, value, onChange, prefix, aspectClass = "aspect-square", hint,
}: {
  label: string;
  value: string | null;
  onChange: (url: string | null) => void;
  prefix: UploadPrefix;
  aspectClass?: string;
  hint?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  async function handleFile(file: File) {
    if (!file.type.startsWith("image/")) {
      setError("That is not an image. Pictures only here.");
      return;
    }
    setUploading(true);
    setError(null);
    const result = await uploadImage(prefix, file);
    setUploading(false);
    if (result.ok) onChange(result.url);
    else setError(result.error);
  }

  /** The clipboard carries images as files; a copied web image may also
   *  arrive as a URL, which is not ours to hotlink, so it is refused. */
  function fromClipboard(data: DataTransfer | null) {
    const file = Array.from(data?.files ?? []).find((f) => f.type.startsWith("image/"));
    if (file) {
      void handleFile(file);
      return true;
    }
    const item = Array.from(data?.items ?? []).find((i) => i.type.startsWith("image/"));
    const asFile = item?.getAsFile();
    if (asFile) {
      void handleFile(asFile);
      return true;
    }
    return false;
  }

  return (
    <div>
      <Label>{label}</Label>
      <div
        // Focusable, so a paste lands here. role=button + Enter/Space keeps it
        // operable from the keyboard, which a bare div would not be.
        role="button"
        tabIndex={0}
        aria-label={`${label}: upload, drop or paste an image`}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onPaste={(e) => {
          if (fromClipboard(e.clipboardData)) e.preventDefault();
          else setError("There was no image in what you pasted. Copy the image itself, then paste.");
        }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!fromClipboard(e.dataTransfer)) setError("That was not an image file.");
        }}
        className={`relative w-full cursor-pointer overflow-hidden rounded-lg border border-dashed bg-[var(--surface-2)] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--heading)] ${aspectClass} ${
          over ? "border-[var(--heading)] bg-[color-mix(in_srgb,var(--heading)_8%,var(--surface-2))]" : "border-[var(--border)]"
        }`}
      >
        {value ? (
          <Image src={value} alt={label} fill sizes="320px" className="object-cover" />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 px-3 text-center text-xs text-[var(--muted)]">
            <span>Click, drop a file, or paste</span>
            <span aria-hidden="true">⌘V / Ctrl+V</span>
          </div>
        )}
        {over && !uploading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 text-sm font-medium text-white">
            Drop to upload
          </div>
        )}
        {uploading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 text-sm font-medium text-white">
            Uploading…
          </div>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
          e.target.value = "";
        }}
      />
      <div className="mt-2.5 flex items-center gap-2">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="min-h-9 cursor-pointer rounded-lg border border-[var(--border)] px-3 text-xs font-semibold disabled:opacity-50"
        >
          {value ? "Replace" : "Upload"}
        </button>
        {value && (
          <button type="button" onClick={() => onChange(null)} className="min-h-9 cursor-pointer rounded-lg px-3 text-xs font-semibold text-[var(--status-critical)]">
            Remove
          </button>
        )}
      </div>
      {hint && <p className="mt-1.5 text-xs text-[var(--muted)]">{hint}</p>}
      {error && <p role="alert" className="mt-1.5 text-xs text-[var(--status-critical)]">{error}</p>}
    </div>
  );
}
