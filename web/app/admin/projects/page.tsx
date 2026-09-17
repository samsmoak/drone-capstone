import { ProjectsManager } from "@/components/admin/ProjectsManager";
import { getAllProjectsAdmin } from "@/lib/queries";

export const metadata = { title: "Projects · Admin" };

export default async function AdminProjectsPage() {
  const projects = await getAllProjectsAdmin();
  return <ProjectsManager initial={projects} />;
}
