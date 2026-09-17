import { redirect } from "next/navigation";
import { ADMIN_PROJECTS } from "@/lib/routes";

export default function AdminHome() {
  redirect(ADMIN_PROJECTS);
}
