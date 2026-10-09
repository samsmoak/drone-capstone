/**
 * Who ran a session or flew a flight: the name, and the email beneath it.
 *
 * Both come from the record itself (operator_name, operator_email), stamped by
 * the database from the owner's profile — migration 20261009000015. A record
 * uploaded before then, or with no owner at all, says so in words rather than
 * a dash, so "nobody recorded" is never mistaken for "nobody".
 *
 * The email is data, not a label: it wears the foreground colour and wraps
 * anywhere rather than being cut off on a narrow screen.
 */

type Who = { operator_name: string | null; operator_email: string | null };

const NOT_RECORDED = "Not recorded";

/** For a table cell. */
export function Owner({ who }: { who: Who }) {
  if (!who.operator_name && !who.operator_email) {
    return <span className="text-[var(--muted)]">{NOT_RECORDED}</span>;
  }
  return (
    <span className="flex flex-col">
      <span>{who.operator_name || who.operator_email}</span>
      {who.operator_name && who.operator_email && (
        <span className="break-all text-xs">{who.operator_email}</span>
      )}
    </span>
  );
}

/** For a page's summary, beside the other Stat tiles. */
export function OwnerStat({ label, who }: { label: string; who: Who }) {
  const known = Boolean(who.operator_name || who.operator_email);
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{label}</p>
      {known ? (
        <>
          <p className="mt-1 text-lg font-semibold text-[var(--foreground)]">
            {who.operator_name || who.operator_email}
          </p>
          {who.operator_name && who.operator_email && (
            <p className="break-all text-sm text-[var(--foreground)]">{who.operator_email}</p>
          )}
        </>
      ) : (
        <p className="mt-1 text-lg font-semibold text-[var(--muted)]">{NOT_RECORDED}</p>
      )}
    </div>
  );
}
