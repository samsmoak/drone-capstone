// Copied from ../doctor-portfolio/lib/video.ts.
// YouTube URL handling. Pure — safe on the server and the client.

/**
 * Pull the video id out of any YouTube URL shape people actually paste:
 * youtu.be/ID, /watch?v=ID, /embed/ID, /shorts/ID, /live/ID — with or without
 * tracking params like ?si=…
 */
export function youtubeId(url: string | null | undefined): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  if (/^[\w-]{11}$/.test(trimmed)) return trimmed;

  try {
    const u = new URL(trimmed);
    const host = u.hostname.replace(/^www\./, "");

    if (host === "youtu.be") {
      const id = u.pathname.slice(1).split("/")[0];
      return /^[\w-]{11}$/.test(id) ? id : null;
    }
    if (host.endsWith("youtube.com") || host.endsWith("youtube-nocookie.com")) {
      const v = u.searchParams.get("v");
      if (v && /^[\w-]{11}$/.test(v)) return v;
      const m = u.pathname.match(/\/(embed|shorts|live|v)\/([\w-]{11})/);
      if (m) return m[2];
    }
  } catch {
    /* not a URL */
  }
  return null;
}

export const isYouTube = (url: string | null | undefined) => youtubeId(url) !== null;

/** Poster frame. `maxresdefault` isn't generated for every video, so callers
 *  should be able to fall back to `hqdefault`, which always exists. */
export function youtubeThumb(id: string, quality: "max" | "hq" = "max"): string {
  return `https://i.ytimg.com/vi/${id}/${quality === "max" ? "maxresdefault" : "hqdefault"}.jpg`;
}

/** Privacy-preserving embed host; `autoplay` only ever follows a user click. */
export function youtubeEmbed(id: string, { autoplay = false } = {}): string {
  const params = new URLSearchParams({
    rel: "0",
    modestbranding: "1",
    playsinline: "1",
    ...(autoplay ? { autoplay: "1" } : {}),
  });
  return `https://www.youtube-nocookie.com/embed/${id}?${params}`;
}

export function youtubeWatch(id: string): string {
  return `https://www.youtube.com/watch?v=${id}`;
}

/** A picture or a video, wherever the CMS lets an owner choose either. */
export type MediaItem = {
  kind: "image" | "video";
  url: string;
  caption?: string;
};

export function toMediaItem(
  imageUrl: string | null | undefined,
  videoUrl: string | null | undefined,
  caption?: string,
): MediaItem | null {
  if (videoUrl?.trim()) return { kind: "video", url: videoUrl.trim(), caption };
  if (imageUrl?.trim()) return { kind: "image", url: imageUrl.trim(), caption };
  return null;
}
