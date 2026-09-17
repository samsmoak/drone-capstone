"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { createProject, deleteProject, reorderProjects, setProjectStatus } from "@/lib/mutations";
import type { ProjectCard } from "@/lib/queries";
import { adminProjectPath, projectPath } from "@/lib/routes";
import { Button, Card, Input, StatusChip } from "./ui";

/** Create, publish, order and delete projects. Copied from ../doctor-portfolio. */
export function ProjectsManager({ initial }: { initial: ProjectCard[] }) {
  const router = useRouter();
  const [items, setItems] = useState(initial);
  const [newTitle, setNewTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [busyId, setBusyId] = useState<string | null>(null);

  function create() {
    const title = newTitle.trim();
    if (!title) return;
    setError(null);
    startTransition(async () => {
      const res = await createProject({ title });
      if (res.ok) router.push(adminProjectPath(res.data.id));
      else setError(res.error);
    });
  }

  function togglePublish(p: ProjectCard) {
    const next = p.status === "published" ? "draft" : "published";
    setBusyId(p.id);
    startTransition(async () => {
      const res = await setProjectStatus(p.id, next);
      if (res.ok) setItems((prev) => prev.map((it) => (it.id === p.id ? { ...it, status: next } : it)));
      else setError(res.error);
      setBusyId(null);
      router.refresh();
    });
  }

  function remove(p: ProjectCard) {
    if (!confirm(`Delete “${p.title}”? This cannot be undone.`)) return;
    setBusyId(p.id);
    startTransition(async () => {
      const res = await deleteProject(p.id);
      if (res.ok) setItems((prev) => prev.filter((it) => it.id !== p.id));
      else setError(res.error);
      setBusyId(null);
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
      const res = await reorderProjects(next.map((it, i) => ({ id: it.id, position: i + 1 })));
      if (!res.ok) setError(res.error);
      router.refresh();
    });
  }

  return (
    <div className="grid gap-6">
      <header>
        <h1 className="font-display text-3xl font-semibold">Projects</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Create, write up, publish and order the projects on the public site.
        </p>
      </header>

      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <Input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()}
          placeholder="New project title…"
          aria-label="New project title"
          className="flex-1"
        />
        <Button onClick={create} disabled={pending || !newTitle.trim()}>+ Create project</Button>
      </Card>

      {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-16 text-center text-[var(--muted)]">
          No projects yet. Create the first one above.
        </div>
      ) : (
        <ul className="grid gap-3">
          {items.map((p, i) => (
            <li key={p.id}>
              <Card className={`flex flex-wrap items-center gap-4 p-4 ${busyId === p.id ? "opacity-60" : ""}`}>
                <div className="flex flex-col">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0 || pending}
                          aria-label={`Move ${p.title} up`} className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▲</button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === items.length - 1 || pending}
                          aria-label={`Move ${p.title} down`} className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▼</button>
                </div>
                <div className="min-w-0 flex-1">
                  <Link href={adminProjectPath(p.id)} className="font-medium hover:underline">
                    {p.title || "Untitled"}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <StatusChip status={p.status} />
                    <span className="text-xs text-[var(--muted)]">{projectPath(p.slug)}</span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  <Button variant="outline" onClick={() => togglePublish(p)} disabled={pending}>
                    {p.status === "published" ? "Unpublish" : "Publish"}
                  </Button>
                  <Link href={adminProjectPath(p.id)}
                        className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-semibold">
                    Edit
                  </Link>
                  <Button variant="danger" onClick={() => remove(p)} disabled={pending} aria-label={`Delete ${p.title}`}>
                    Delete
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
