import { notFound } from "next/navigation";
import { AlbumEditor } from "@/components/admin/AlbumEditor";
import { getAlbumByIdAdmin } from "@/lib/queries";

export const metadata = { title: "Edit album · Admin" };

export default async function EditAlbumPage({ params }: PageProps<"/admin/gallery/[id]">) {
  const { id } = await params;
  const album = await getAlbumByIdAdmin(id);
  if (!album) notFound();
  // Keyed by the items, so adding photos or a video (a server refresh) gives the
  // editor the new list instead of keeping its stale copy.
  return <AlbumEditor key={album.items.map((i) => i.id).join(",")} album={album} />;
}
