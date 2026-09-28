import Link from "next/link";
import { DashboardLink, VisitorAccount } from "@/components/site/VisitorAccount";
import { Nav } from "@/components/ui/nav";
import { ThemeToggle } from "@/components/site/ThemeToggle";
import { Wordmark } from "@/components/site/Wordmark";
import { getCurrentProfile, getPageContent } from "@/lib/queries";
import { SITE_CONTAINER, WIDE_CONTAINER, WIDE_PAGES } from "@/lib/layout";
import { HOME, PUBLIC_NAV, SETUP } from "@/lib/routes";
import { text } from "@/lib/site-content";

/**
 * The visitor site. Signed in or not, this is what you see here — the operator
 * screens open from Dashboard, and their "Visitor site" link comes back.
 */
export default async function PublicLayout({ children }: { children: React.ReactNode }) {
  const [profile, site] = await Promise.all([getCurrentProfile(), getPageContent("site")]);
  const account = profile ? { email: profile.email, name: profile.full_name, role: profile.role } : null;

  return (
    <>
      <Nav
        brand={<Wordmark />}
        brandLabel="DroneDeck — home"
        brandHref={HOME}
        items={PUBLIC_NAV}
        cta={<DashboardLink />}
        actions={<ThemeToggle />}
        trailing={<VisitorAccount account={account} />}
        wide={{ prefixes: WIDE_PAGES, width: WIDE_CONTAINER }}
      />
      <div id="main">{children}</div>
      <footer className="mt-20 border-t border-[var(--border)]">
        <div className={`${SITE_CONTAINER} py-8 text-sm text-[var(--muted)]`}>
          {text(site, "footerText")}{" "}
          <Link href={SETUP} className="underline underline-offset-4">{text(site, "footerLinkLabel")}</Link>.
        </div>
      </footer>
    </>
  );
}
