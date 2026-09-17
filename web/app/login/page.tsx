import { LoginForm } from "@/components/ui/login-form";

export const metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-2 text-sm text-[var(--muted)]">
        Sign in with your CropWatcher account. You stay on the page you came from — open
        the Dashboard whenever you want the operator screens.
      </p>
      <LoginForm next={next} />
    </main>
  );
}
