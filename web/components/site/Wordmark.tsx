import Image from "next/image";

/**
 * The DroneDeck wordmark: the drone mark, then "Drone" in the ink colour and
 * "Deck" in the heading colour, set in Space Grotesk (.font-brand).
 *
 * "Deck" takes --heading, not --primary: it is text, and --heading is the
 * token measured to clear 4.5:1 on every surface in both themes.
 *
 * The mark is decorative beside the name (alt=""), so a screen reader hears
 * "DroneDeck" once, from the text.
 */
const SIZES = {
  sm: { mark: 28, text: "text-lg" },
  md: { mark: 34, text: "text-xl" },
  lg: { mark: 56, text: "text-4xl sm:text-5xl" },
} as const;

export function Wordmark({ size = "sm", showMark = true }: { size?: keyof typeof SIZES; showMark?: boolean }) {
  const s = SIZES[size];
  return (
    <span className="inline-flex items-center gap-2.5">
      {showMark && (
        <Image
          src="/brand/drone-mark-256.png"
          alt=""
          width={s.mark}
          height={s.mark}
          priority
          className="shrink-0"
        />
      )}
      <span className={`font-brand ${s.text} leading-none`}>
        <span className="font-medium">Drone</span>
        <span className="font-bold text-[var(--heading)]">Deck</span>
      </span>
    </span>
  );
}
