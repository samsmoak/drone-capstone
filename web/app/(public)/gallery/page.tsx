import type { Metadata } from "next";
import { AlbumGrid } from "@/components/gallery/AlbumGrid";
import { PhotoIcon, PlayIcon } from "@/components/gallery/icons";
import { getPublishedAlbums } from "@/lib/queries";

export const metadata: Metadata = {
  title: "Gallery",
  description: "Photos and videos of CropWatcher: the hardware, the team, and drones in flight.",
};

export default async function GalleryPage() {
  const albums = await getPublishedAlbums();
  const photos = albums.reduce((n, a) => n + a.photoCount, 0);
  const videos = albums.reduce((n, a) => n + a.videoCount, 0);

  return (
    <main className="mx-auto max-w-6xl px-6 py-16 md:py-20">
      <p className="eyebrow text-[var(--heading)]">Gallery</p>
      <h1 className="font-display mt-3 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
        The kit, the team, and the drone in the air
      </h1>
      <p className="mt-4 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">
        Photos and videos from building and flying CropWatcher, grouped into albums.
      </p>
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
