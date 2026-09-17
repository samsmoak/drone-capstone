import { redirect } from "next/navigation";
import { ADMIN_PAGES } from "@/lib/routes";

export default function AdminHome() {
  redirect(ADMIN_PAGES);
}
