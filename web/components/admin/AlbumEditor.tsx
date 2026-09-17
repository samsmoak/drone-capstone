"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import {
  addGalleryItems,
  deleteAlbum,
  deleteGalleryItem,
  reorderGalleryItems,
  updateAlbum,
  updateGalleryItem,
  type NewGalleryItem,
} from "@/lib/mutations";
import type { AlbumWithItems, GalleryItemRow } from "@/lib/queries";
import { ADMIN_GALLERY, galleryPath } from "@/lib/routes";
import { uploadImage } from "@/lib/upload";
import { youtubeId, youtubeThumb } from "@/lib/video";
import { Button, Card, Input, Label, StatusChip, Textarea } from "./ui";

/** Read an image's size in the browser, so the public page can lay it out before it loads. */
function measure(file: File): Promise<{ width: number | null; height: number | null }> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new window.Image();
    img.onload = () => { resolve({ width: img.naturalWidth, height: img.naturalHeight }); URL.revokeObjectURL(url); };
    img.onerror = () => { resolve({ width: null, height: null }); URL.revokeObjectURL(url); };
    img.src = url;
  });
}

export function AlbumEditor({ album }: { album: AlbumWithItems }) {
  const router = useRouter();
  const [title, setTitle] = useState(album.title);
  const [summary, setSummary] = useState(album.summary);
  const [category, setCategory] = useState(album.category);
  const [dateLabel, setDateLabel] = useState(album.date_label);
  const [cover, setCover] = useState<string | null>(album.cover_image_url);
  const [status, setStatus] = useState(album.status as "draft" | "published");
  const [items, setItems] = useState<GalleryItemRow[]>(album.items);
  const [videoUrl, setVideoUrl] = useState("");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const fileInput = useRef<HTMLInputElement>(null);

  const fail = (text: string) => setMessage({ tone: "error", text });

  function save(nextStatus?: "draft" | "published") {
    setMessage(null);
    startTransition(async () => {
      const res = await updateAlbum(album.id, {
        title, summary, category, date_label: dateLabel, cover_image_url: cover, status: nextStatus ?? status,
      });
      if (!res.ok) return fail(res.error);
      if (nextStatus) setStatus(nextStatus);
      setMessage({ tone: "ok", text: "Saved ✓" });
      router.refresh();
    });
  }

  async function uploadFiles(files: FileList) {
    setMessage(null);
    const added: NewGalleryItem[] = [];
    const list = Array.from(files);
    for (const [n, file] of list.entries()) {
      setUploading(`Uploading ${n + 1} of ${list.length}…`);
      const size = await measure(file);
      const result = await uploadImage("gallery", file);
      if (!result.ok) { setUploading(null); return fail(result.error); }
      added.push({ kind: "image", url: result.url, ...size });
    }
    setUploading("Adding to the album…");
    const res = await addGalleryItems(album.id, added);
    setUploading(null);
    if (!res.ok) return fail(res.error);
    router.refresh();
  }

  function addVideo() {
    const url = videoUrl.trim();
    if (!youtubeId(url)) return fail("That is not a YouTube link. Paste a youtube.com or youtu.be address.");
    startTransition(async () => {
      const res = await addGalleryItems(album.id, [{ kind: "video", url }]);
      if (!res.ok) return fail(res.error);
      setVideoUrl("");
      router.refresh();
    });
  }

  function saveItem(item: GalleryItemRow) {
    startTransition(async () => {
      const res = await updateGalleryItem(item.id, { caption: item.caption, credit: item.credit });
      if (!res.ok) fail(res.error);
      else setMessage({ tone: "ok", text: "Caption saved ✓" });
    });
  }

  function removeItem(item: GalleryItemRow) {
    if (!confirm("Remove this from the album?")) return;
    startTransition(async () => {
      const res = await deleteGalleryItem(item.id);
      if (!res.ok) return fail(res.error);
      setItems((prev) => prev.filter((it) => it.id !== item.id));
      router.refresh();
    });
  }

  function move(index: number, dir: -1 | 1) {
    const target = index + dir;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    setItems(next);
    startTransition(async () => {
      const res = await reorderGalleryItems(next.map((it, i) => ({ id: it.id, position: i })));
      if (!res.ok) fail(res.error);
      router.refresh();
    });
  }

  function removeAlbum() {
    if (!confirm(`Delete “${title || "this album"}” and everything in it?`)) return;
    startTransition(async () => {
      const res = await deleteAlbum(album.id);
      if (res.ok) router.push(ADMIN_GALLERY);
      else fail(res.error);
    });
  }

  const setField = (id: string, key: "caption" | "credit", value: string) =>
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, [key]: value } : it)));

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Link href={ADMIN_GALLERY} className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]">← Gallery</Link>
          <StatusChip status={status} />
          {message && (
            <span role={message.tone === "error" ? "alert" : "status"}
                  className={`text-sm font-medium ${message.tone === "error" ? "text-[var(--status-critical)]" : ""}`}>
              {message.text}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {status === "published" && (
            <Link href={galleryPath(album.slug)} target="_blank" className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-semibold">View ↗</Link>
          )}
          <Button variant="outline" onClick={() => save()} disabled={pending}>Save</Button>
          {status === "published"
            ? <Button variant="ghost" onClick={() => save("draft")} disabled={pending}>Unpublish</Button>
            : <Button onClick={() => save("published")} disabled={pending}>Publish</Button>}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="grid content-start gap-5 p-6">
          <div><Label htmlFor="a-title">Title</Label><Input id="a-title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
          <div><Label htmlFor="a-summary">Summary</Label><Textarea id="a-summary" rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label htmlFor="a-cat">Category</Label><Input id="a-cat" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Team" /></div>
            <div><Label htmlFor="a-date">Date</Label><Input id="a-date" value={dateLabel} onChange={(e) => setDateLabel(e.target.value)} placeholder="2026" /></div>
          </div>
          <p className="text-xs text-[var(--muted)]">The album card uses its first photos. Pick a cover below for search and sharing.</p>
          <Button variant="danger" onClick={removeAlbum} disabled={pending} className="justify-start px-0">Delete album</Button>
        </Card>

        <div className="grid content-start gap-6 lg:col-span-2">
          <Card className="grid gap-4 p-6">
            <Label>Add photos</Label>
            <input ref={fileInput} type="file" accept="image/*" multiple className="hidden"
                   onChange={(e) => { if (e.target.files?.length) void uploadFiles(e.target.files); e.target.value = ""; }} />
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => fileInput.current?.click()} disabled={!!uploading}>Upload photos</Button>
              {uploading && <span role="status" className="text-sm text-[var(--muted)]">{uploading}</span>}
            </div>
            <Label htmlFor="video-url">Add a YouTube video</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input id="video-url" value={videoUrl} onChange={(e) => setVideoUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
              <Button variant="outline" onClick={addVideo} disabled={pending || !videoUrl.trim()}>Add video</Button>
            </div>
          </Card>

          {items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--border)] p-12 text-center text-[var(--muted)]">Nothing in this album yet.</div>
          ) : (
            <ul className="grid gap-3">
              {items.map((item, i) => {
                const vid = item.kind === "video" ? youtubeId(item.url) : null;
                const thumb = vid ? youtubeThumb(vid, "hq") : item.url;
                return (
                  <li key={item.id}>
                    <Card className="flex flex-wrap items-start gap-4 p-4">
                      <div className="flex flex-col">
                        <button type="button" onClick={() => move(i, -1)} disabled={i === 0 || pending} aria-label="Move up" className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▲</button>
                        <button type="button" onClick={() => move(i, 1)} disabled={i === items.length - 1 || pending} aria-label="Move down" className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▼</button>
                      </div>
                      <div className="relative h-20 w-28 shrink-0 overflow-hidden rounded-lg bg-[var(--surface-2)]">
                        <Image src={thumb} alt="" fill sizes="112px" className="object-cover" unoptimized={!!vid} />
                        {vid && <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 text-[10px] font-semibold text-white">VIDEO</span>}
                      </div>
                      <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2">
                        <Input aria-label="Caption" value={item.caption} placeholder="Caption" onChange={(e) => setField(item.id, "caption", e.target.value)} />
                        <Input aria-label="Credit" value={item.credit} placeholder="Credit" onChange={(e) => setField(item.id, "credit", e.target.value)} />
                      </div>
                      <div className="flex flex-wrap gap-1">
                        <Button variant="outline" onClick={() => saveItem(item)} disabled={pending}>Save</Button>
                        {item.kind === "image" && (
                          <Button variant={cover === item.url ? "primary" : "ghost"} onClick={() => setCover(item.url)} disabled={pending}>
                            {cover === item.url ? "Cover" : "Make cover"}
                          </Button>
                        )}
                        <Button variant="danger" onClick={() => removeItem(item)} disabled={pending}>Remove</Button>
                      </div>
                    </Card>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
