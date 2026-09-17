import { getCurrentProfile } from "@/lib/queries";
import { OperatorMobileNav } from "./OperatorMobileNav";
import { OperatorSidebar } from "./OperatorSidebar";

/**
 * The frame every operator page sits in — /app and /admin alike, so the two
 * look like one place. A fixed left sidebar on wide screens (the layout of
 * ../doctor-portfolio's admin studio), a slim sticky bar on phones.
 */
export async function OperatorShell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const profile = await getCurrentProfile();
  const account = profile ? { email: profile.email, name: profile.full_name, role: profile.role } : null;
  const isOperator = profile?.role === "operator";

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <div className="fixed inset-y-0 left-0 hidden w-64 border-r border-[var(--border)] bg-[var(--surface)] lg:block">
        <OperatorSidebar account={account} isOperator={isOperator} />
      </div>
      <div className="lg:pl-64">
        <OperatorMobileNav account={account} isOperator={isOperator} />
        <main id="main" className={`mx-auto w-full px-5 py-8 sm:px-8 sm:py-10 ${wide ? "max-w-[96rem]" : "max-w-6xl"}`}>
          {children}
        </main>
      </div>
    </div>
  );
}
