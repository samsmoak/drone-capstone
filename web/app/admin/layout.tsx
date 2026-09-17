import Link from "next/link";
import { OperatorShell } from "@/components/operator/OperatorShell";
import { getCurrentProfile } from "@/lib/queries";
import { OPERATOR_HOME } from "@/lib/routes";

/**
 * The website admin. Operators only.
 *
 * The check here decides what to render; what an account can actually write is
 * decided by public.is_operator() in RLS on every request. Navigation lives in
 * the shared operator sidebar, under "Website".
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const profile = await getCurrentProfile();
  const allowed = profile?.role === "operator";

  return (
    <OperatorShell wide>
      {allowed ? (
        children
      ) : (
        <div className="max-w-xl rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8">
          <h1 className="font-display text-2xl font-semibold">Operators only</h1>
          <p className="mt-2 text-[var(--muted)]">
            The website admin edits what the public sees, so it needs an operator account. Ask an
            operator to change your role.
          </p>
          <Link href={OPERATOR_HOME} className="mt-4 inline-block underline underline-offset-4">
            Back to the dashboard
          </Link>
        </div>
      )}
    </OperatorShell>
  );
}
