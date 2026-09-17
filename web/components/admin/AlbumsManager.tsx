"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { createAlbum, deleteAlbum, reorderAlbums, setAlbumStatus } from "@/lib/mutations";
import type { AlbumCard } from "@/lib/queries";
import { adminAlbumPath, galleryPath } from "@/lib/routes";
import { Button, Card, Input, StatusChip } from "./ui";

/** Create, publish, order and delete gallery albums. Same shape as ProjectsManager. */
export function AlbumsManager({ initial }: { initial: AlbumCard[] }) {
  const router = useRouter();
  const [items, setItems] = useState(initial);
  const [newTitle, setNewTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function create() {
    const title = newTitle.trim();
    if (!title) return;
    setError(null);
    startTransition(async () => {
      const res = await createAlbum({ title });
      if (res.ok) router.push(adminAlbumPath(res.data.id));
      else setError(res.error);
    });
  }

  function togglePublish(a: AlbumCard) {
    const next = a.status === "published" ? "draft" : "published";
    startTransition(async () => {
      const res = await setAlbumStatus(a.id, next);
      if (res.ok) setItems((prev) => prev.map((it) => (it.id === a.id ? { ...it, status: next } : it)));
      else setError(res.error);
      router.refresh();
    });
  }

  function remove(a: AlbumCard) {
    if (!confirm(`Delete the album “${a.title}” and everything in it? This cannot be undone.`)) return;
    startTransition(async () => {
      const res = await deleteAlbum(a.id);
      if (res.ok) setItems((prev) => prev.filter((it) => it.id !== a.id));
      else setError(res.error);
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
      const res = await reorderAlbums(next.map((it, i) => ({ id: it.id, position: i + 1 })));
      if (!res.ok) setError(res.error);
      router.refresh();
    });
  }

  return (
    <div className="grid gap-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Gallery</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">Albums of photos and videos on the public gallery. The order here is the order shown.</p>
      </header>

      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <Input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()}
               placeholder="New album title…" aria-label="New album title" className="flex-1" />
        <Button onClick={create} disabled={pending || !newTitle.trim()}>+ Create album</Button>
      </Card>

      {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-16 text-center text-[var(--muted)]">No albums yet.</div>
      ) : (
        <ul className="grid gap-3">
          {items.map((a, i) => (
            <li key={a.id}>
              <Card className="flex flex-wrap items-center gap-4 p-4">
                <div className="flex flex-col">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0 || pending} aria-label={`Move ${a.title} up`} className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▲</button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === items.length - 1 || pending} aria-label={`Move ${a.title} down`} className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▼</button>
                </div>
                <div className="relative h-14 w-20 shrink-0 overflow-hidden rounded-lg bg-[var(--surface-2)]">
                  {(a.preview[0]?.url ?? a.cover_image_url) && (
                    <Image src={a.preview[0]?.url ?? a.cover_image_url!} alt="" fill sizes="80px" className="object-cover" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <Link href={adminAlbumPath(a.id)} className="font-medium hover:underline">{a.title || "Untitled"}</Link>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                    <StatusChip status={a.status} />
                    <span>{a.photoCount} photos · {a.videoCount} videos</span>
                    <span>{galleryPath(a.slug)}</span>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  <Button variant="outline" onClick={() => togglePublish(a)} disabled={pending}>
                    {a.status === "published" ? "Unpublish" : "Publish"}
                  </Button>
                  <Link href={adminAlbumPath(a.id)} className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-semibold">Edit</Link>
                  <Button variant="danger" onClick={() => remove(a)} disabled={pending}>Delete</Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
