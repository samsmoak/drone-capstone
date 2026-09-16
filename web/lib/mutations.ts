"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { FLIGHTS, PLAN } from "@/lib/routes";
import { getZones } from "@/lib/queries";
import { buildPlan, parsePlanInput, validatePlan } from "@/lib/mission-plan";

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

/**
 * Queue a mission built in the planner.
 *
 * Takes zone ids and settings, never waypoints. The plan is rebuilt here from
 * the zones table and validated with the same rules the planner shows, because
 * a Server Action is a public endpoint: whatever the browser claims to have
 * built, only what the server builds reaches the agent. RLS still decides
 * whether this user may insert at all.
 */
export async function queuePlannedMission(raw: unknown): Promise<ActionResult & { problems?: string[] }> {
  const input = parsePlanInput(raw);
  if (!input) return { ok: false, error: "That plan could not be read. Reload the page and try again." };

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not signed in." };

  let zones;
  try {
    zones = await getZones();
  } catch {
    return { ok: false, error: "Could not load the zones to check this plan. Please try again." };
  }

  const unknown = input.zoneIds.filter((id) => !zones.some((z) => z.id === id));
  if (unknown.length > 0) {
    return { ok: false, error: "Some chosen zones no longer exist. Reload the page and choose again." };
  }

  const plan = buildPlan(input, zones);
  const problems = validatePlan(plan);
  if (problems.length > 0) {
    return { ok: false, error: "This plan is not safe to queue yet.", problems };
  }

  const { data, error } = await supabase
    .from("missions")
    .insert({ name: plan.name, type: plan.type, plan: plan as never, created_by: user.id })
    .select("id")
    .single();

  if (error) {
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

  const { data, error } = await supabase
    .from("missions")
    .update({ status: "cancelled" })
    .eq("id", missionId)
    // Only a mission that has not been picked up can be cancelled here.
    // One already claimed is stopped through the agent, not the database.
    .eq("status", "queued")
    // An update that matches nothing is not an error to Postgres — the agent
    // claimed it a moment ago, or RLS filtered it out. Without counting rows
    // the operator is told "cancelled" about a mission that is about to fly.
    .select("id");

  if (error) {
    return { ok: false, error: "Could not cancel that mission." };
  }
  if (data.length === 0) {
    // Refresh anyway: the row on screen still says "queued", and the real
    // status is the most useful thing to show next to this message.
    revalidatePath(PLAN);
    return {
      ok: false,
      error:
        "That mission was not cancelled: it has already been picked up by the agent, or your account cannot change it. Stop a flight in progress from the desktop app.",
    };
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
