/**
 * The layout measurement the harness exists for.
 *
 * `pages-and-windows.txt` carries the rule: *measure the layout, do not eyeball
 * it*. This is the part that measures. Loading `harness.html?measure=1` walks
 * the rendered DOM and reports every element that crosses the viewport, into a
 * <pre> the page shows and a headless browser can read with --dump-dom:
 *
 *   "$CHROME" --headless=new --disable-gpu --window-size=720,900 \
 *     --virtual-time-budget=2500 \
 *     --dump-dom 'http://localhost:5199/harness.html?measure=1'
 *
 * `?theme=dark|light` forces the tokens, so both themes are measured rather
 * than whichever one the machine happens to be set to.
 *
 * `?selftest=1` plants one over-wide element and MUST report FAIL. Run it
 * alongside the real pass — see plantOverflow below for why.
 *
 * Note headless Chrome clamps --window-size to a minimum width of 500, so a
 * narrower control case than that cannot be measured this way.
 *
 * Not shipped: `vite build` only builds index.html, and nothing in the app
 * imports this.
 */

/** A rect may exceed the viewport by this much before it counts — sub-pixel
 *  rounding puts a flush-right border at 720.004 on a fractional-DPR display. */
const SLOP_PX = 1.5;

export type Overflow = { selector: string; right: number; left: number };

function describe(el: Element): string {
  const classes = (el.getAttribute("class") ?? "").split(/\s+/).filter(Boolean).slice(0, 4);
  const id = el.id ? `#${el.id}` : "";
  return `${el.tagName.toLowerCase()}${id}${classes.length ? `.${classes.join(".")}` : ""}`;
}

export function findOverflow(): Overflow[] {
  const width = document.documentElement.clientWidth;
  const out: Overflow[] = [];

  for (const el of Array.from(document.body.querySelectorAll("*"))) {
    // An element inside its own scroll container is allowed to be wider than
    // the viewport — that is what the container is for. Only overflow that
    // reaches the PAGE is a layout fault.
    if (isInsideScroller(el)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    if (rect.right > width + SLOP_PX || rect.left < -SLOP_PX) {
      out.push({ selector: describe(el), right: Math.round(rect.right), left: Math.round(rect.left) });
    }
  }
  return out;
}

/**
 * Is this element inside something that genuinely scrolls sideways?
 *
 * BOTH conditions are needed, and the second one is the whole point. Setting
 * `overflow-y: auto` alone — which `main` and every console pane do — makes the
 * browser resolve `overflow-x` to `auto` as well, even though nothing ever
 * scrolls horizontally. Checking the property by itself therefore treated the
 * entire page as "inside a scroller" and the measurement passed vacuously,
 * proving nothing. Requiring real horizontal scroll extent (scrollWidth beyond
 * clientWidth) is what distinguishes the readings table, which does scroll
 * sideways and is allowed to, from `main`, which does not.
 */
function isInsideScroller(el: Element): boolean {
  let node = el.parentElement;
  while (node && node !== document.body) {
    const overflow = getComputedStyle(node).overflowX;
    const scrollable = overflow === "auto" || overflow === "scroll";
    if (scrollable && node.scrollWidth > node.clientWidth + SLOP_PX) return true;
    node = node.parentElement;
  }
  return false;
}

/**
 * Prove the detector can fail.
 *
 * `?selftest=1` plants one deliberately over-wide element and expects the
 * report to catch it. Without this, a PASS is indistinguishable from a
 * measurement that silently checks nothing — which is exactly what happened
 * once already, when `overflow-x` resolving to `auto` made isInsideScroller
 * skip the whole page. A clean run of the suite is only meaningful next to a
 * failing run of this.
 */
function plantOverflow() {
  const bad = document.createElement("div");
  bad.id = "selftest-overflow";
  bad.style.cssText = "width:3000px;height:4px;background:red";
  document.body.appendChild(bad);
}

/** Render the report into the page, where --dump-dom will pick it up. */
export function reportInto(id: string) {
  if (new URLSearchParams(location.search).has("selftest")) plantOverflow();
  const width = document.documentElement.clientWidth;
  const theme = document.documentElement.dataset.theme ?? "system";
  const overflow = findOverflow();
  const pageScroll = document.documentElement.scrollWidth - width;

  const lines = [
    `MEASURE width=${width} theme=${theme}`,
    `page-scroll-overflow=${pageScroll > SLOP_PX ? `${Math.round(pageScroll)}px FAIL` : "0 OK"}`,
    `elements-crossing-viewport=${overflow.length}${overflow.length === 0 ? " OK" : " FAIL"}`,
    ...overflow.slice(0, 20).map((o) => `  ${o.selector}  left=${o.left} right=${o.right}`),
    overflow.length > 20 ? `  …and ${overflow.length - 20} more` : "",
    `RESULT ${overflow.length === 0 && pageScroll <= SLOP_PX ? "PASS" : "FAIL"}`,
  ].filter(Boolean);

  const pre = document.createElement("pre");
  pre.id = id;
  pre.textContent = lines.join("\n");
  pre.style.cssText = "position:fixed;inset:auto 0 0 0;z-index:9999;background:#000;color:#0f0;font:12px monospace;padding:8px;margin:0";
  document.body.appendChild(pre);
}
