import { GROUPS, SEVERITY, groupColor, groupTint, type Group, type Mark, type Severity } from "@/lib/pipeline";

/**
 * The key to the pipeline's highlights, the same wherever they appear — the
 * readings table, the error table, the charts' bands, the frames (the owner,
 * 2026-10-09): the HUE is the data group, the DEPTH of the tint the severity.
 * Each group's swatch is shown at its three depths, with the words.
 */

/** Never colour alone: the severity's shape, in the group's colour. */
const SHAPE: Record<Severity, string> = { critical: "■", warning: "▲", info: "●" };

export function MarkShape({ mark }: { mark: Pick<Mark, "group" | "severity"> }) {
  return (
    <span aria-hidden="true" className="text-[11px] leading-none" style={{ color: groupColor(mark.group) }}>
      {SHAPE[mark.severity]}
    </span>
  );
}

const ORDER: Severity[] = ["info", "warning", "critical"];

export function MarkLegend({ groups }: { groups: Group[] }) {
  const shown = (Object.keys(GROUPS) as Group[]).filter((g) => groups.includes(g));
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs" role="group"
         aria-label="What the colours mean">
      {shown.map((g) => (
        <span key={g} className="inline-flex items-center gap-2">
          <span className="font-semibold">{GROUPS[g].label}</span>
          {ORDER.map((s) => (
            <span key={s} className="inline-flex items-center gap-1">
              <span aria-hidden="true" className="inline-block h-4 w-5 rounded-sm border border-[var(--border)]"
                    style={{ background: groupTint(g, s) }} />
              <MarkShape mark={{ group: g, severity: s }} />
              <span>{SEVERITY[s].label}</span>
            </span>
          ))}
        </span>
      ))}
    </div>
  );
}
