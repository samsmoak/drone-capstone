"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import { uploadImage, type UploadPrefix } from "@/lib/upload";
import { Label } from "./ui";

/** Upload or replace one image. Copied from ../doctor-portfolio. */
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

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    const result = await uploadImage(prefix, file);
    setUploading(false);
    if (result.ok) onChange(result.url);
    else setError(result.error);
  }

  return (
    <div>
      <Label>{label}</Label>
      <div className={`relative w-full overflow-hidden rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface-2)] ${aspectClass}`}>
        {value ? (
          <Image src={value} alt={label} fill sizes="320px" className="object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-[var(--muted)]">No image</div>
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
          className="min-h-9 rounded-lg border border-[var(--border)] px-3 text-xs font-semibold disabled:opacity-50"
        >
          {value ? "Replace" : "Upload"}
        </button>
        {value && (
          <button type="button" onClick={() => onChange(null)} className="min-h-9 rounded-lg px-3 text-xs font-semibold text-[var(--status-critical)]">
            Remove
          </button>
        )}
      </div>
      {hint && <p className="mt-1.5 text-xs text-[var(--muted)]">{hint}</p>}
      {error && <p role="alert" className="mt-1.5 text-xs text-[var(--status-critical)]">{error}</p>}
    </div>
  );
}
