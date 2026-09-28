// PARITY: web/components/site/Wordmark.tsx — same mark, face and colours.
// Adapted only in rendering: a plain <img> (no next/image here), and the
// sidebar's collapsed state shows the mark alone.

/**
 * The DroneDeck wordmark: the drone mark, "Drone" in the ink colour and "Deck"
 * in --heading (text, so the heading token that clears 4.5:1 in both themes),
 * set in Space Grotesk (.font-brand), bundled with the app.
 */
export function Wordmark({ showName = true }: { showName?: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <img src="/brand/drone-mark-256.png" alt="" width={32} height={32} className="h-8 w-8 shrink-0" />
      {showName && (
        <span className="font-brand truncate text-lg leading-none">
          <span className="font-medium">Drone</span>
          <span className="font-bold text-[var(--heading)]">Deck</span>
        </span>
      )}
    </span>
  );
}
