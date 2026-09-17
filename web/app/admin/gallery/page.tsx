import { AlbumsManager } from "@/components/admin/AlbumsManager";
import { getAllAlbumsAdmin } from "@/lib/queries";

export const metadata = { title: "Gallery · Admin" };

export default async function AdminGalleryPage() {
  const albums = await getAllAlbumsAdmin();
  return <AlbumsManager initial={albums} />;
}
