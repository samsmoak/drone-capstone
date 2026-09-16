import { Nav } from "@/components/ui/nav";
import { PUBLIC_NAV, OPERATOR_HOME, SETUP } from "@/lib/routes";
import Link from "next/link";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav
        brand="CropWatcher"
        items={PUBLIC_NAV}
        trailing={
          <Link
            href={OPERATOR_HOME}
            className="inline-flex min-h-11 items-center rounded-md border border-[var(--border)] px-3 text-sm"
          >
            Operator sign in
          </Link>
        }
      />
      <div id="main">{children}</div>
      <footer className="mt-20 border-t border-[var(--border)]">
        <div className="mx-auto max-w-6xl px-6 py-8 text-sm text-[var(--muted)]">
          CropWatcher — capstone project. Built on a Crazyflie 2.1.{" "}
          <Link href={SETUP} className="underline underline-offset-4">
            Set up the system
          </Link>
          .
        </div>
      </footer>
    </>
  );
}
