import Link from "next/link";
import { ThemeToggle } from "@/components/site/ThemeToggle";
import { Wordmark } from "@/components/site/Wordmark";
import { LoginForm } from "@/components/ui/login-form";
import { HOME } from "@/lib/routes";

export const metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <div className="mb-10 flex items-center justify-between gap-3">
        <Link href={HOME} aria-label="DroneDeck — home" className="flex min-h-11 items-center">
          <Wordmark size="md" />
        </Link>
        <ThemeToggle />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-2 text-sm text-[var(--muted)]">
        Sign in with your DroneDeck account — the same one the desktop app uses. You stay on
        the page you came from; open the Dashboard whenever you want the operator screens.
      </p>
      <LoginForm next={next} />
    </main>
  );
}
