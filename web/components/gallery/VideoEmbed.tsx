"use client";

import Image from "next/image";
import { useState } from "react";
import { youtubeEmbed, youtubeId, youtubeThumb } from "@/lib/video";

/**
 * A YouTube video that shows its poster first and loads the player on click.
 *
 * Copied from ../doctor-portfolio/components/media/VideoEmbed.tsx: embedding the
 * iframe up front loads a large third-party player and starts tracking for a
 * video most visitors never play.
 */
export function VideoEmbed({ url, title = "Video", className = "" }: { url: string; title?: string; className?: string }) {
  const id = youtubeId(url);
  const [playing, setPlaying] = useState(false);
  // maxresdefault isn't generated for every upload; hqdefault always is.
  const [thumb, setThumb] = useState(() => (id ? youtubeThumb(id, "max") : ""));

  if (!id) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer"
         className={`flex min-h-11 items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-3 text-sm font-semibold ${className}`}>
        {title} ↗
      </a>
    );
  }

  return (
    <div className={`relative aspect-video w-full overflow-hidden rounded-xl bg-black ${className}`}>
      {playing ? (
        <iframe
          src={youtubeEmbed(id, { autoplay: true })}
          title={title}
          className="absolute inset-0 h-full w-full"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
          referrerPolicy="strict-origin-when-cross-origin"
        />
      ) : (
        <button type="button" onClick={() => setPlaying(true)} aria-label={`Play ${title}`}
                className="group absolute inset-0 h-full w-full cursor-pointer">
          <Image src={thumb} alt="" fill sizes="(max-width: 768px) 100vw, 640px" unoptimized
                 className="object-cover transition-transform duration-500 group-hover:scale-[1.03]"
                 onError={() => setThumb(youtubeThumb(id, "hq"))} />
          <span className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-black/20" />
          <span className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/95 text-black shadow-xl transition-transform duration-200 group-hover:scale-110">
            <svg viewBox="0 0 24 24" fill="currentColor" className="ml-1 h-7 w-7" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" /></svg>
          </span>
        </button>
      )}
    </div>
  );
}
