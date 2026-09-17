import { notFound } from "next/navigation";
import { ProjectEditor } from "@/components/admin/ProjectEditor";
import { getProjectByIdAdmin, getTeamMembers } from "@/lib/queries";

export const metadata = { title: "Edit project · Admin" };

export default async function EditProjectPage({ params }: PageProps<"/admin/projects/[id]">) {
  const { id } = await params;
  const [project, team] = await Promise.all([getProjectByIdAdmin(id), getTeamMembers()]);
  if (!project) notFound();
  return <ProjectEditor project={project} allMembers={team} />;
}
