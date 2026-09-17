"use client";

import { createClient } from "@/lib/supabase/client";

/**
 * Image uploads for the portfolio admin.
 *
 * Copied from ../doctor-portfolio's lib/upload.ts. The bucket is public-read
 * and operator-write (migration 0007): RLS is the gate, and the size and type
 * checks here only give a readable refusal before a wasted upload.
 */

export type UploadPrefix = "covers" | "team" | "content";

const BUCKET = "portfolio-images";
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function extensionFor(file: File): string {
  const fromName = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
  return fromName || file.type.split("/")[1] || "bin";
}

export type UploadResult = { ok: true; url: string } | { ok: false; error: string };

export async function uploadImage(prefix: UploadPrefix, file: File): Promise<UploadResult> {
  if (!file.type.startsWith("image/")) return { ok: false, error: "Only images can be uploaded here." };
  if (file.size > MAX_IMAGE_BYTES) {
    return { ok: false, error: `That image is ${(file.size / 1e6).toFixed(1)} MB. The limit is 10 MB.` };
  }
  try {
    const supabase = createClient();
    const rand = Math.random().toString(36).slice(2, 8);
    const path = `${prefix}/${Date.now()}-${rand}.${extensionFor(file)}`;
    const { error } = await supabase.storage.from(BUCKET).upload(path, file, {
      cacheControl: "3600",
      upsert: false,
      contentType: file.type || undefined,
    });
    if (error) return { ok: false, error: "Upload failed. Check you are signed in as an operator." };
    return { ok: true, url: supabase.storage.from(BUCKET).getPublicUrl(path).data.publicUrl };
  } catch {
    return { ok: false, error: "Upload failed. Check your connection and try again." };
  }
}

/** BlockNote's `uploadFile` handler. */
export async function uploadFileForEditor(file: File): Promise<string> {
  const result = await uploadImage("content", file);
  if (!result.ok) throw new Error(result.error);
  return result.url;
}
