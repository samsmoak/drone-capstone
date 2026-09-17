import { notFound } from "next/navigation";
import { PageEditor } from "@/components/admin/PageEditor";
import { getEditedPages, getPageContent } from "@/lib/queries";
import { isPageKey } from "@/lib/site-content";

export const metadata = { title: "Edit page · Admin" };

export default async function EditPagePage({ params }: PageProps<"/admin/pages/[key]">) {
  const { key } = await params;
  if (!isPageKey(key)) notFound();
  const [content, edited] = await Promise.all([getPageContent(key), getEditedPages()]);
  return <PageEditor pageKey={key} initial={content} edited={edited.has(key)} />;
}
