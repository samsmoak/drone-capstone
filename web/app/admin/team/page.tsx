import { TeamManager } from "@/components/admin/TeamManager";
import { getTeamMembers } from "@/lib/queries";

export const metadata = { title: "Team · Admin" };

export default async function AdminTeamPage() {
  const team = await getTeamMembers();
  return <TeamManager initial={team} />;
}
