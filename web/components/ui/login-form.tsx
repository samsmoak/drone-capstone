"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient, isSupabaseConfigured } from "@/lib/supabase/client";
import { OPERATOR_HOME } from "@/lib/routes";
import { ErrorState } from "@/components/ui/states";

/**
 * Email/password and Google, side by side.
 *
 * Both are offered because they solve different problems: email/password works
 * with no external configuration, and Google saves the group another password.
 * They produce the same session, so everything downstream is identical.
 */
export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const destination = next ?? OPERATOR_HOME;

  if (!isSupabaseConfigured()) {
    return (
      <div className="mt-6">
        <ErrorState
          title="Sign-in is not configured"
          detail="NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are missing from .env.local."
        />
      </div>
    );
  }

  async function signInWithPassword(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);

    const supabase = createClient();
    const { error: authError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (authError) {
      // One message for both wrong-email and wrong-password: distinguishing
      // them tells an attacker which accounts exist.
      setError("That email and password do not match an account.");
      setPending(false);
      return;
    }

    router.push(destination);
    router.refresh();
  }

  async function signInWithGoogle() {
    setPending(true);
    setError(null);
    const supabase = createClient();
    const { error: authError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(destination)}`,
      },
    });
    if (authError) {
      setError("Could not start Google sign-in. Try email and password.");
      setPending(false);
    }
  }

  return (
    <div className="mt-8">
      <form onSubmit={signInWithPassword} className="space-y-4">
        <div>
          <label htmlFor="email" className="block text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3"
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3"
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-[var(--status-critical)]">
            {error}
          </p>
        )}

        <button
          type="submit"
          // Disabled in flight, so a double submit cannot fire two sign-ins.
          disabled={pending}
          className="min-h-11 w-full rounded-lg bg-[var(--primary)] font-medium text-[var(--on-primary)] disabled:opacity-60"
        >
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="my-6 flex items-center gap-3 text-xs text-[var(--muted)]">
        <span className="h-px flex-1 bg-[var(--border)]" />
        or
        <span className="h-px flex-1 bg-[var(--border)]" />
      </div>

      <button
        type="button"
        onClick={signInWithGoogle}
        disabled={pending}
        className="min-h-11 w-full rounded-lg border border-[var(--border)] font-medium disabled:opacity-60"
      >
        Continue with Google
      </button>
    </div>
  );
}
