import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import type { Database } from "@/types/database";
import { HOME, LOGIN, isProtectedPath, safeNext } from "@/lib/routes";

/**
 * Session refresh plus the gate on /app and /admin.
 *
 * This is UX, not security. It decides what to *render*; what a user can
 * actually read or write is decided by RLS in Postgres on every request. A
 * middleware check alone would be bypassable by calling the API directly.
 */
export async function updateSession(request: NextRequest) {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const pathname = request.nextUrl.pathname;

  // Not configured yet: keep the public showcase and the login page reachable,
  // bounce the gated area. A fresh clone should still show something.
  if (!supabaseUrl || !supabaseAnonKey) {
    if (isProtectedPath(pathname)) {
      const url = request.nextUrl.clone();
      url.pathname = LOGIN;
      return NextResponse.redirect(url);
    }
    return NextResponse.next({ request });
  }

  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient<Database>(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value),
        );
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options),
        );
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (isProtectedPath(pathname) && !user) {
    const url = request.nextUrl.clone();
    url.pathname = LOGIN;
    // Remember where they were headed so login can return them there.
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  // Already signed in: go where sign-in was headed, else the visitor home —
  // signing in never switches you into the operator view by itself.
  if (user && pathname === LOGIN) {
    const url = request.nextUrl.clone();
    url.pathname = safeNext(request.nextUrl.searchParams.get("next")) ?? HOME;
    url.search = "";
    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}
