import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { OPERATOR_HOME } from "@/lib/routes";

/** OAuth lands here. Exchanges the code for a session, then sends them on. */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? OPERATOR_HOME;

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // Never dump the provider error into the URL — it can carry identifiers.
  return NextResponse.redirect(`${origin}/login?error=auth`);
}
