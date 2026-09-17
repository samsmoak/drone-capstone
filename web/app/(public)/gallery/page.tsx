import { SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import { AlbumGrid } from "@/components/gallery/AlbumGrid";
import { PhotoIcon, PlayIcon } from "@/components/gallery/icons";
import { PageIntro } from "@/components/site/PageIntro";
import { getPageContent, getPublishedAlbums } from "@/lib/queries";

export const metadata: Metadata = {
  title: "Gallery",
  description: "Photos and videos of CropWatcher: the hardware, the team, and drones in flight.",
};

export default async function GalleryPage() {
  const [albums, intro] = await Promise.all([getPublishedAlbums(), getPageContent("gallery")]);
  const photos = albums.reduce((n, a) => n + a.photoCount, 0);
  const videos = albums.reduce((n, a) => n + a.videoCount, 0);

  return (
    <main className={`${SITE_CONTAINER} py-16 md:py-20`}>
      <PageIntro content={intro} />
      {albums.length > 0 && (
        <p className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-[var(--muted)]">
          <span className="font-medium text-[var(--foreground)]">{albums.length} albums</span>
          <span className="inline-flex items-center gap-1.5"><PhotoIcon /> {photos} photos</span>
          <span className="inline-flex items-center gap-1.5"><PlayIcon className="h-3.5 w-3.5" /> {videos} videos</span>
        </p>
      )}

      {albums.length === 0 ? (
        <div className="mt-16 rounded-xl border border-dashed border-[var(--border)] p-16 text-center">
          <p className="text-[var(--muted)]">No albums published yet.</p>
        </div>
      ) : (
        <AlbumGrid albums={albums} />
      )}
    </main>
  );
}
