/**
 * The Auto flow's step bar: ① Plan ─ ② Position ─ ③ Flyable space ─
 * ④ Auto-correct ─ ⑤ Fly.
 *
 * Adapted from the Zoomaa booking flow's stepper (booking_flow_screen.dart,
 * "An animated, tappable stepper"): each step is a real button, completed steps
 * carry a check, the current one is filled, and any step already reachable can
 * be jumped to. A step that cannot be reached yet is disabled WITH THE REASON —
 * as a tooltip and as words below the bar — never silently dead.
 *
 * aria-current="step" marks where the operator is (WAI-ARIA 1.2).
 *
 * NEVER SQUEEZED (2026-10-05, Samuel): every label is shown whole. Wide, the
 * steps share the width; narrow, the bar scrolls sideways instead of
 * squashing — the list is never narrower than its own content (min-w-max).
 */

export type FlowStep = 1 | 2 | 3 | 4 | 5;

export type StepState = {
  step: FlowStep;
  label: string;
  done: boolean;
  /** Why it cannot be opened now; null when it can. */
  blocked: string | null;
};

export function StepBar({ steps, current, onSelect }: {
  steps: StepState[];
  current: FlowStep;
  onSelect: (step: FlowStep) => void;
}) {
  const blockedHere = steps.find((s) => s.step === current + 1)?.blocked ?? null;
  return (
    <nav aria-label="Mission steps" className="grid min-w-0 gap-1.5">
      <div className="overflow-x-auto pb-1">
      <ol className="flex w-full min-w-max items-stretch">
        {steps.map((s, i) => {
          const active = s.step === current;
          return (
            <li key={s.step} className="flex flex-1 items-center">
              <button
                type="button"
                onClick={() => onSelect(s.step)}
                disabled={s.blocked !== null && !active}
                title={s.blocked ?? undefined}
                aria-current={active ? "step" : undefined}
                className={`flex min-h-10 flex-1 items-center gap-2 whitespace-nowrap border px-3 text-left text-xs font-semibold uppercase tracking-[0.06em] disabled:cursor-not-allowed disabled:opacity-45 ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
                    : s.done
                      ? "border-[var(--primary)] bg-[var(--surface)] text-[var(--heading)]"
                      : "border-[var(--border)] bg-[var(--surface)] text-[var(--foreground)]"
                }`}
              >
                <span aria-hidden="true" className="mono inline-flex h-5 w-5 shrink-0 items-center justify-center border border-current text-[11px]">
                  {s.done && !active ? "✓" : s.step}
                </span>
                <span>{s.label}</span>
                {s.done && <span className="sr-only"> — done</span>}
              </button>
              {i < steps.length - 1 && (
                <span aria-hidden="true" className={`h-0.5 w-3 shrink-0 ${s.done ? "bg-[var(--primary)]" : "bg-[var(--border)]"}`} />
              )}
            </li>
          );
        })}
      </ol>
      </div>
      {blockedHere && (
        <p className="text-xs text-[var(--muted)]">
          Next: {blockedHere}
        </p>
      )}
    </nav>
  );
}
