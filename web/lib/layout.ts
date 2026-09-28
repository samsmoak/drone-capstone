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

/**
 * The wider frame for pages with three columns — a project write-up has its
 * contents, the article and the team side by side, and at 72rem the article
 * was left about 630 px (2026-09-28). The navbar switches to this width on the
 * same pages (WIDE_PAGES), so the edges still line up.
 */
export const WIDE_CONTAINER = "mx-auto w-full max-w-[90rem] px-6";

/** Path prefixes whose pages use WIDE_CONTAINER. "/projects/" is the write-ups, not the list. */
export const WIDE_PAGES = ["/projects/"] as const;

/** About 75 characters at body size — the comfortable reading measure. */
export const PROSE_COLUMN = "max-w-3xl";
