"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { BlockEditorClient } from "@/components/editor/BlockEditorClient";
import { deleteProject, updateProject } from "@/lib/mutations";
import type { ProjectWithTeam, TeamMemberRow } from "@/lib/queries";
import { ADMIN_PROJECTS, ADMIN_TEAM, projectPath } from "@/lib/routes";
import type { Json } from "@/types/database";
import { ImagePicker } from "./ImagePicker";
import { Button, Card, Input, Label, StatusChip, Textarea } from "./ui";

type SaveState = { kind: "idle" | "saved" | "error"; message?: string };

/**
 * Edit one project. Copied from ../doctor-portfolio's ProjectEditor; the
 * highlight toggle and media galleries were dropped, and a team picker was added
 * — the people ticked here appear beside the project on the public page.
 */
export function ProjectEditor({ project, allMembers }: { project: ProjectWithTeam; allMembers: TeamMemberRow[] }) {
  const router = useRouter();
  const [title, setTitle] = useState(project.title);
  const [subtitle, setSubtitle] = useState(project.subtitle);
  const [summary, setSummary] = useState(project.summary);
  const [category, setCategory] = useState(project.category);
  const [dateLabel, setDateLabel] = useState(project.date_label);
  const [location, setLocation] = useState(project.location);
  const [coverUrl, setCoverUrl] = useState<string | null>(project.cover_image_url);
  const [status, setStatus] = useState(project.status as "draft" | "published");
  const [memberIds, setMemberIds] = useState<string[]>(project.team.map((m) => m.id));
  const contentRef = useRef<Json>(project.content);
  const [state, setState] = useState<SaveState>({ kind: "idle" });
  const [pending, startTransition] = useTransition();

  function save(nextStatus?: "draft" | "published") {
    setState({ kind: "idle" });
    startTransition(async () => {
      const res = await updateProject(project.id, {
        title, subtitle, summary, category,
        date_label: dateLabel, location, cover_image_url: coverUrl,
        content: contentRef.current,
        status: nextStatus ?? status,
        member_ids: memberIds,
      });
      if (res.ok) {
        if (nextStatus) setStatus(nextStatus);
        setState({ kind: "saved" });
        router.refresh();
      } else {
        setState({ kind: "error", message: res.error });
      }
    });
  }

  function toggleMember(id: string) {
    setMemberIds((prev) => (prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]));
  }

  function remove() {
    if (!confirm(`Delete “${title || "this project"}”? This cannot be undone.`)) return;
    startTransition(async () => {
      const res = await deleteProject(project.id);
      if (res.ok) router.push(ADMIN_PROJECTS);
      else setState({ kind: "error", message: res.error });
    });
  }

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Link href={ADMIN_PROJECTS} className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]">← Projects</Link>
          <StatusChip status={status} />
          {state.kind === "saved" && <span role="status" className="text-sm font-medium">Saved ✓</span>}
          {state.kind === "error" && <span role="alert" className="text-sm font-medium text-[var(--status-critical)]">{state.message}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {status === "published" && (
            <Link href={projectPath(project.slug)} target="_blank"
                  className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-semibold">
              View ↗
            </Link>
          )}
          <Button variant="outline" onClick={() => save()} disabled={pending}>{pending ? "Saving…" : "Save"}</Button>
          {status === "published"
            ? <Button variant="ghost" onClick={() => save("draft")} disabled={pending}>Unpublish</Button>
            : <Button onClick={() => save("published")} disabled={pending}>Publish</Button>}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="grid content-start gap-6">
          <Card className="grid gap-5 p-6">
            <div><Label htmlFor="title">Title</Label><Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div><Label htmlFor="subtitle">Subtitle</Label><Input id="subtitle" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} /></div>
            <div><Label htmlFor="summary">Summary (card blurb)</Label><Textarea id="summary" rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label htmlFor="category">Category</Label><Input id="category" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Flight" /></div>
              <div><Label htmlFor="date">Date</Label><Input id="date" value={dateLabel} onChange={(e) => setDateLabel(e.target.value)} placeholder="Fall 2026" /></div>
            </div>
            <div><Label htmlFor="location">Location</Label><Input id="location" value={location} onChange={(e) => setLocation(e.target.value)} /></div>
          </Card>

          <Card className="p-6">
            <ImagePicker label="Cover image" value={coverUrl} onChange={setCoverUrl} prefix="covers" aspectClass="aspect-[16/9]" />
          </Card>

          <Card className="p-6">
            <Label>Team on this project</Label>
            {allMembers.length === 0 ? (
              <p className="text-sm text-[var(--muted)]">
                No team members yet. <Link href={ADMIN_TEAM} className="underline">Add them</Link> first.
              </p>
            ) : (
              <ul className="grid gap-1">
                {allMembers.map((m) => (
                  <li key={m.id}>
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 hover:bg-[var(--surface-2)]">
                      <input type="checkbox" checked={memberIds.includes(m.id)} onChange={() => toggleMember(m.id)} className="h-4 w-4" />
                      <span className="text-sm">{m.full_name}{m.role && <span className="text-[var(--muted)]"> · {m.role}</span>}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-[var(--muted)]">Shown beside the project in the order ticked.</p>
          </Card>

          <Card className="p-6">
            <Label>Permalink</Label>
            <p className="break-all font-mono text-xs text-[var(--muted)]">{projectPath(project.slug)}</p>
            <Button variant="danger" onClick={remove} disabled={pending} className="mt-3 px-0">Delete project</Button>
          </Card>
        </div>

        <div className="lg:col-span-2">
          <Card className="p-6 sm:p-8">
            <Label>Write-up</Label>
            <p className="mb-4 text-xs text-[var(--muted)]">Headings become the page&apos;s contents. Type “/” for blocks, or drag images in.</p>
            <BlockEditorClient initialContent={project.content} onChange={(doc) => { contentRef.current = doc; }} />
          </Card>
        </div>
      </div>
    </div>
  );
}
