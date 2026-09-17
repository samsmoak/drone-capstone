import Link from "next/link";
import { Nav } from "@/components/ui/nav";
import { getCurrentProfile } from "@/lib/queries";
import { ADMIN_NAV, HOME, OPERATOR_HOME, OPERATOR_NAV } from "@/lib/routes";
import { signOut } from "@/lib/mutations";

/**
 * The portfolio admin. Operators only.
 *
 * The check here decides what to render; what an account can actually write is
 * decided by public.is_operator() in RLS on every request (migration 0007).
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const profile = await getCurrentProfile();
  const allowed = profile?.role === "operator";

  return (
    <>
      <Nav
        brand="CropWatcher"
        brandHref={HOME}
        items={OPERATOR_NAV}
        trailing={
          <form action={signOut}>
            <button type="submit" className="min-h-11 rounded-md border border-[var(--border)] px-3 text-sm">
              Sign out
            </button>
          </form>
        }
      />
      <main id="main" className="mx-auto max-w-6xl px-6 py-8">
        {allowed ? (
          <div className="grid gap-8 lg:grid-cols-[12rem_minmax(0,1fr)]">
            <nav aria-label="Admin" className="lg:sticky lg:top-8 lg:self-start">
              <p className="eyebrow mb-3">Website admin</p>
              <ul className="flex gap-1 lg:grid">
                {ADMIN_NAV.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="inline-flex min-h-11 w-full items-center rounded-md px-3 text-sm hover:bg-[var(--surface-2)]"
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <div className="min-w-0">{children}</div>
          </div>
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
      </main>
    </>
  );
}
