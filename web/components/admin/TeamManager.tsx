"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { createMember, deleteMember, reorderMembers, updateMember, type MemberInput } from "@/lib/mutations";
import type { TeamMemberRow } from "@/lib/queries";
import { ImagePicker } from "./ImagePicker";
import { Button, Card, Input, Label, Textarea } from "./ui";

const EMPTY: MemberInput = { full_name: "", role: "", bio: "", avatar_url: null, website_url: null, email: null };

function toInput(m: TeamMemberRow): MemberInput {
  return { full_name: m.full_name, role: m.role, bio: m.bio, avatar_url: m.avatar_url, website_url: m.website_url, email: m.email };
}

/** Add, edit, order and remove team members. The order here is the order on /team. */
export function TeamManager({ initial }: { initial: TeamMemberRow[] }) {
  const router = useRouter();
  const [items, setItems] = useState(initial);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<MemberInput>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function open(member: TeamMemberRow | null) {
    setError(null);
    setEditing(member ? member.id : "new");
    setDraft(member ? toInput(member) : EMPTY);
  }

  function save() {
    setError(null);
    startTransition(async () => {
      const res = editing === "new" ? await createMember(draft) : await updateMember(editing!, draft);
      if (!res.ok) { setError(res.error); return; }
      setEditing(null);
      router.refresh();
    });
  }

  function remove(m: TeamMemberRow) {
    if (!confirm(`Remove ${m.full_name} from the team? They are also removed from every project.`)) return;
    startTransition(async () => {
      const res = await deleteMember(m.id);
      if (res.ok) setItems((prev) => prev.filter((it) => it.id !== m.id));
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
      const res = await reorderMembers(next.map((it, i) => ({ id: it.id, position: i + 1 })));
      if (!res.ok) setError(res.error);
      router.refresh();
    });
  }

  const set = <K extends keyof MemberInput>(key: K, value: MemberInput[K]) => setDraft((d) => ({ ...d, [key]: value }));

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold">Team</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">The people on /team and beside each project. The order here is the order shown.</p>
        </div>
        <Button onClick={() => open(null)} disabled={pending}>+ Add member</Button>
      </header>

      {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}

      {editing && (
        <Card className="grid gap-6 p-6 md:grid-cols-[14rem_minmax(0,1fr)]">
          <ImagePicker label="Photo" value={draft.avatar_url} onChange={(url) => set("avatar_url", url)} prefix="team" />
          <div className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div><Label htmlFor="m-name">Name</Label><Input id="m-name" value={draft.full_name} onChange={(e) => set("full_name", e.target.value)} /></div>
              <div><Label htmlFor="m-role">Role</Label><Input id="m-role" value={draft.role} onChange={(e) => set("role", e.target.value)} placeholder="Flight software" /></div>
              <div><Label htmlFor="m-web">Website</Label><Input id="m-web" value={draft.website_url ?? ""} onChange={(e) => set("website_url", e.target.value)} placeholder="https://" /></div>
              <div><Label htmlFor="m-email">Email</Label><Input id="m-email" type="email" value={draft.email ?? ""} onChange={(e) => set("email", e.target.value)} /></div>
            </div>
            <div><Label htmlFor="m-bio">Bio</Label><Textarea id="m-bio" rows={3} value={draft.bio} onChange={(e) => set("bio", e.target.value)} /></div>
            <div className="flex gap-2">
              <Button onClick={save} disabled={pending || !draft.full_name.trim()}>{pending ? "Saving…" : "Save"}</Button>
              <Button variant="ghost" onClick={() => setEditing(null)} disabled={pending}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--border)] p-16 text-center text-[var(--muted)]">No team members yet.</div>
      ) : (
        <ul className="grid gap-3">
          {items.map((m, i) => (
            <li key={m.id}>
              <Card className="flex flex-wrap items-center gap-4 p-4">
                <div className="flex flex-col">
                  <button type="button" onClick={() => move(i, -1)} disabled={i === 0 || pending} aria-label={`Move ${m.full_name} up`} className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▲</button>
                  <button type="button" onClick={() => move(i, 1)} disabled={i === items.length - 1 || pending} aria-label={`Move ${m.full_name} down`} className="min-h-6 px-1 text-[var(--muted)] disabled:opacity-30">▼</button>
                </div>
                <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-[var(--surface-2)]">
                  {m.avatar_url
                    ? <Image src={m.avatar_url} alt="" fill sizes="48px" className="object-cover" />
                    : <span className="font-display flex h-full w-full items-center justify-center text-lg">{m.full_name.charAt(0)}</span>}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{m.full_name}</p>
                  <p className="wrap-anywhere text-xs text-[var(--muted)]">
                    {[m.role, m.website_url, m.email].filter(Boolean).join(" · ") || "No details yet"}
                  </p>
                </div>
                <div className="flex gap-1">
                  <Button variant="outline" onClick={() => open(m)} disabled={pending}>Edit</Button>
                  <Button variant="danger" onClick={() => remove(m)} disabled={pending}>Remove</Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
