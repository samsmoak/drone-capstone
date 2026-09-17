/**
 * One container for the visitor site.
 *
 * The navbar and every page use it, so their left and right edges line up down
 * the whole site. Pages used to pick their own width — the navbar at 72rem, the
 * home page at 64rem, Set Up and Hardware at 48rem — and every page looked
 * inset by a different amount.
 *
 * Long-form pages keep a readable line length by holding their *text* to
 * PROSE_COLUMN inside the full-width frame, rather than by narrowing the frame.
 */
export const SITE_CONTAINER = "mx-auto w-full max-w-6xl px-6";

/** About 75 characters at body size — the comfortable reading measure. */
export const PROSE_COLUMN = "max-w-3xl";
