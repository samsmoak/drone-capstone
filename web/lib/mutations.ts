"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { FLIGHTS, PLAN } from "@/lib/routes";

/**
 * Every write goes through this file.
 *
 * These are Server Actions, so they run with the caller's cookie-bound session
 * and RLS applies. The role checks here are for a useful error message; the
 * enforcement is `is_operator()` in Postgres. Never move enforcement up here —
 * a client can call the API directly.
 */

export type ActionResult =
  | { ok: true; id?: string }
  | { ok: false; error: string };

export async function queueMission(
  plan: Record<string, unknown>,
  name: string,
  type: "hover" | "lawnmower" | "waypoint",
): Promise<ActionResult> {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not signed in." };

  const { data, error } = await supabase
    .from("missions")
    .insert({ name, type, plan: plan as never, created_by: user.id })
    .select("id")
    .single();

  if (error) {
    // Do not leak the raw Postgres message: it can carry column names and
    // policy internals. Map the one case an operator can act on.
    const friendly =
      error.code === "42501"
        ? "Your account is not an operator, so it cannot queue flights."
        : "Could not queue the mission. Please try again.";
    return { ok: false, error: friendly };
  }

  revalidatePath(PLAN);
  return { ok: true, id: data.id };
}

export async function cancelMission(missionId: string): Promise<ActionResult> {
  const supabase = await createClient();

  const { error } = await supabase
    .from("missions")
    .update({ status: "cancelled" })
    .eq("id", missionId)
    // Only a mission that has not been picked up can be cancelled here.
    // One already claimed is stopped through the agent, not the database.
    .eq("status", "queued");

  if (error) {
    return { ok: false, error: "Could not cancel that mission." };
  }

  revalidatePath(PLAN);
  return { ok: true };
}

export async function deleteFlight(flightId: string): Promise<ActionResult> {
  const supabase = await createClient();
  const { error } = await supabase.from("flights").delete().eq("id", flightId);

  if (error) {
    return { ok: false, error: "Could not delete that flight." };
  }

  revalidatePath(FLIGHTS);
  return { ok: true };
}

export async function signOut(): Promise<void> {
  const supabase = await createClient();
  await supabase.auth.signOut();
  revalidatePath("/", "layout");
}
