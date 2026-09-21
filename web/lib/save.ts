"use client";

import type { PortfolioResult } from "@/lib/mutations";

/**
 * Run a save and always come back with an answer.
 *
 * A Server Action can REJECT rather than return: the request was too large,
 * the network dropped, the deployment restarted mid-call. An editor that only
 * handled `{ ok: false }` let that rejection escape the transition, where it
 * reached the route's error boundary and replaced the page — taking everything
 * typed since the last save (2026-09-21).
 *
 * Nothing that can be caught here is allowed past.
 */
export async function attempt<T>(
  run: () => Promise<PortfolioResult<T>>,
): Promise<PortfolioResult<T>> {
  try {
    return await run();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("save failed before it reached the database", error);
    if (/body exceeded|too large|payload|413/i.test(message)) {
      return { ok: false, error:
        "This is too large to save in one go — usually images pasted into the text rather " +
        "than uploaded. Wait for any \u201cUploading pasted image\u201d notice to finish, or " +
        "remove the largest images and add them again with the image button. Nothing was " +
        "saved, and what you typed is still here." };
    }
    if (/fetch|network|load failed/i.test(message)) {
      return { ok: false, error:
        "Could not reach the site to save this. Check your connection and press Save again — " +
        "what you typed is still here." };
    }
    return { ok: false, error:
      "The save did not go through, and nothing was changed. Press Save again — what you " +
      "typed is still here." };
  }
}

/** Roughly how big a document is, for the guard before a save. */
export function sizeOf(value: unknown): number {
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch {
    return 0;
  }
}

/** The Server Action limit set in next.config.ts, less room for the rest of the form. */
export const MAX_SAVE_BYTES = 3_500_000;

export function tooLargeMessage(bytes: number): string {
  return `This write-up is ${(bytes / 1e6).toFixed(1)} MB, which is more than a save can carry. ` +
    `That is almost always images pasted into the text: they are being uploaded in the ` +
    `background, so wait for the notice above the editor to clear and press Save again. ` +
    `Nothing has been lost.`;
}
