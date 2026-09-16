import { Nav } from "@/components/ui/nav";
import { OPERATOR_NAV, HOME } from "@/lib/routes";
import { getCurrentProfile } from "@/lib/queries";
import { signOut } from "@/lib/mutations";

export default async function OperatorLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const profile = await getCurrentProfile();

  return (
    <>
      <Nav
        brand="CropWatcher"
        brandHref={HOME}
        items={OPERATOR_NAV}
        trailing={
          <form action={signOut} className="flex items-center gap-3">
            {profile && (
              <span className="hidden text-sm text-[var(--muted)] sm:inline">
                {profile.full_name ?? profile.email}
                {/* Role is shown because it changes what you can do: a viewer
                    cannot queue flights, and should know that up front. */}
                {profile.role === "viewer" && " · viewer"}
              </span>
            )}
            <button
              type="submit"
              className="min-h-11 rounded-md border border-[var(--border)] px-3 text-sm"
            >
              Sign out
            </button>
          </form>
        }
      />
      <main id="main" className="mx-auto max-w-6xl px-6 py-8">
        {children}
      </main>
    </>
  );
}
