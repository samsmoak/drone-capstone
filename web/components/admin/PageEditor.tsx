"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { resetPageContent, savePageContent } from "@/lib/mutations";
import { ADMIN_PAGES } from "@/lib/routes";
import {
  PAGE_SPECS,
  emptyItem,
  type ContentObject,
  type ContentValue,
  type FieldSpec,
  type PageKey,
} from "@/lib/site-content";
import { ImagePicker } from "./ImagePicker";
import { Button, Card, Input, Label, Textarea } from "./ui";

/**
 * Edit one page's wording. The form is drawn from the page's field spec, so a
 * new editable field is one line in lib/site-content.ts — no new admin screen.
 */
export function PageEditor({ pageKey, initial, edited }: { pageKey: PageKey; initial: ContentObject; edited: boolean }) {
  const spec = PAGE_SPECS[pageKey];
  const router = useRouter();
  const [content, setContent] = useState<ContentObject>(initial);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [pending, startTransition] = useTransition();

  function update(next: ContentObject) {
    setContent(next);
    setDirty(true);
    setMessage(null);
  }

  function save() {
    startTransition(async () => {
      const res = await savePageContent(pageKey, content);
      if (!res.ok) return setMessage({ tone: "error", text: res.error });
      setDirty(false);
      setMessage({ tone: "ok", text: "Saved — the page is updated." });
      router.refresh();
    });
  }

  function reset() {
    if (!confirm(`Put “${spec.title}” back to its original wording? Your edits to this page are lost.`)) return;
    startTransition(async () => {
      const res = await resetPageContent(pageKey);
      if (!res.ok) return setMessage({ tone: "error", text: res.error });
      router.refresh();
      router.push(ADMIN_PAGES);
    });
  }

  return (
    <div className="grid gap-6">
      <header className="sticky top-0 z-20 -mx-2 flex max-lg:top-[6.5rem] flex-wrap items-center justify-between gap-4 rounded-b-xl bg-[var(--background)]/95 px-2 py-3 backdrop-blur">
        <div className="min-w-0">
          <Link href={ADMIN_PAGES} className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]">← Pages</Link>
          <h1 className="font-display mt-1 text-3xl font-semibold">{spec.title}</h1>
          <p className="text-sm text-[var(--muted)]">{spec.description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {message && (
            <span role={message.tone === "error" ? "alert" : "status"}
                  className={`text-sm font-medium ${message.tone === "error" ? "text-[var(--status-critical)]" : ""}`}>
              {message.text}
            </span>
          )}
          {dirty && !message && <span className="text-sm text-[var(--muted)]">Unsaved changes</span>}
          <Link href={spec.path} target="_blank" className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-semibold">
            View page ↗
          </Link>
          {edited && <Button variant="ghost" onClick={reset} disabled={pending}>Reset to original</Button>}
          <Button onClick={save} disabled={pending || !dirty}>{pending ? "Saving…" : "Save"}</Button>
        </div>
      </header>

      <Card className="grid gap-7 p-6 lg:p-8">
        <Fields fields={spec.fields} value={content} onChange={update} />
      </Card>
    </div>
  );
}

// ── the generic form ─────────────────────────────────────────────────────

function Fields({ fields, value, onChange, idPrefix = "f" }: {
  fields: FieldSpec[];
  value: ContentObject;
  onChange: (next: ContentObject) => void;
  idPrefix?: string;
}) {
  // Short fields share a row; long ones take the full width.
  const wide = (f: FieldSpec) => f.type === "textarea" || f.type === "strings" || f.type === "items";
  return (
    <div className="grid gap-6 md:grid-cols-2">
      {fields.map((field) => (
        <div key={field.key} className={wide(field) ? "md:col-span-2" : ""}>
          <Field field={field} id={`${idPrefix}-${field.key}`} value={value[field.key]}
                 onChange={(v) => onChange({ ...value, [field.key]: v })} />
        </div>
      ))}
    </div>
  );
}

function Hint({ text }: { text?: string }) {
  return text ? <p className="mt-1.5 text-xs text-[var(--muted)]">{text}</p> : null;
}

function Field({ field, id, value, onChange }: {
  field: FieldSpec;
  id: string;
  value: ContentValue | undefined;
  onChange: (next: ContentValue) => void;
}) {
  switch (field.type) {
    case "text":
      return (
        <div>
          <Label htmlFor={id}>{field.label}</Label>
          <Input id={id} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />
          <Hint text={field.hint} />
        </div>
      );
    case "textarea":
      return (
        <div>
          <Label htmlFor={id}>{field.label}</Label>
          <Textarea id={id} rows={4} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />
          <Hint text={field.hint} />
        </div>
      );
    case "boolean":
      return (
        <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-[var(--border)] px-4">
          <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4" />
          <span className="text-sm font-medium">{field.label}</span>
        </label>
      );
    case "image":
      return (
        <div className="max-w-md">
          <ImagePicker label={field.label} value={typeof value === "string" && value ? value : null}
                       onChange={(url) => onChange(url ?? "")} prefix="content" aspectClass="aspect-[4/3]" hint={field.hint} />
        </div>
      );
    case "strings": {
      const list = Array.isArray(value) ? (value as unknown[]).filter((v): v is string => typeof v === "string") : [];
      const set = (next: string[]) => onChange(next);
      return (
        <fieldset>
          <legend className="eyebrow mb-3">{field.label}</legend>
          <ol className="grid gap-3">
            {list.map((item, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="tabular mt-3 w-6 shrink-0 text-right text-xs text-[var(--muted)]">{i + 1}</span>
                <Textarea aria-label={`${field.itemLabel} ${i + 1}`} rows={2} value={item} className="flex-1"
                          onChange={(e) => set(list.map((v, j) => (j === i ? e.target.value : v)))} />
                <RowControls index={i} count={list.length} label={field.itemLabel}
                             onMove={(to) => set(move(list, i, to))} onRemove={() => set(list.filter((_, j) => j !== i))} />
              </li>
            ))}
          </ol>
          <Button variant="outline" className="mt-3" onClick={() => set([...list, ""])}>+ Add {field.itemLabel.toLowerCase()}</Button>
          <Hint text={field.hint} />
        </fieldset>
      );
    }
    case "items": {
      const list = Array.isArray(value)
        ? (value as unknown[]).filter((v): v is ContentObject => typeof v === "object" && v !== null && !Array.isArray(v))
        : [];
      const set = (next: ContentObject[]) => onChange(next);
      return (
        <fieldset>
          <legend className="eyebrow mb-3">{field.label}</legend>
          <ol className="grid gap-4">
            {list.map((item, i) => {
              const titleField = field.fields.find((f) => f.type === "text");
              const heading = titleField && typeof item[titleField.key] === "string" ? (item[titleField.key] as string) : "";
              return (
                <li key={i}>
                  <details open={list.length <= 4} className="group rounded-xl border border-[var(--border)] bg-[var(--surface-2)]">
                    <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-5 py-3">
                      <span className="flex min-w-0 items-center gap-3">
                        <span aria-hidden="true" className="text-[var(--muted)] transition-transform group-open:rotate-90">›</span>
                        <span className="eyebrow">{field.itemLabel} {i + 1}</span>
                        <span className="truncate text-sm font-medium">{heading}</span>
                      </span>
                      <RowControls index={i} count={list.length} label={field.itemLabel}
                                   onMove={(to) => set(move(list, i, to))} onRemove={() => set(list.filter((_, j) => j !== i))} />
                    </summary>
                    <div className="border-t border-[var(--border)] bg-[var(--surface)] p-5">
                      <Fields fields={field.fields} value={item} idPrefix={`${id}-${i}`}
                              onChange={(next) => set(list.map((v, j) => (j === i ? next : v)))} />
                    </div>
                  </details>
                </li>
              );
            })}
          </ol>
          <Button variant="outline" className="mt-3" onClick={() => set([...list, emptyItem(field.fields)])}>
            + Add {field.itemLabel.toLowerCase()}
          </Button>
          <Hint text={field.hint} />
        </fieldset>
      );
    }
  }
}

function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

function RowControls({ index, count, label, onMove, onRemove }: {
  index: number; count: number; label: string; onMove: (to: number) => void; onRemove: () => void;
}) {
  // Inside a <summary>, a click would also toggle the section open or shut.
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); fn(); };
  return (
    <span className="flex shrink-0 items-center gap-1">
      <button type="button" onClick={stop(() => onMove(index - 1))} disabled={index === 0}
              aria-label={`Move ${label.toLowerCase()} ${index + 1} up`}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface)] disabled:opacity-30">▲</button>
      <button type="button" onClick={stop(() => onMove(index + 1))} disabled={index === count - 1}
              aria-label={`Move ${label.toLowerCase()} ${index + 1} down`}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface)] disabled:opacity-30">▼</button>
      <button type="button" onClick={stop(onRemove)} aria-label={`Remove ${label.toLowerCase()} ${index + 1}`}
              className="flex h-9 items-center rounded-lg px-2 text-xs font-semibold text-[var(--status-critical)] hover:bg-[var(--surface)]">Remove</button>
    </span>
  );
}
