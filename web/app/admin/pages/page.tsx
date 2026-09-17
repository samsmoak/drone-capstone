import Link from "next/link";
import { getEditedPages } from "@/lib/queries";
import { adminPagePath } from "@/lib/routes";
import { PAGE_KEYS, PAGE_SPECS } from "@/lib/site-content";

export const metadata = { title: "Pages · Admin" };

const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });

/** Every visitor page whose wording can be edited. */
export default async function AdminPagesPage() {
  const edited = await getEditedPages();

  return (
    <div className="grid gap-8">
      <header>
        <h1 className="font-display text-3xl font-semibold">Pages</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--muted)]">
          Every word on the visitor site. Projects, the team and the gallery have their own sections;
          their page headings are edited here.
        </p>
      </header>
      <ul className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {PAGE_KEYS.map((key) => {
          const spec = PAGE_SPECS[key];
          const when = edited.get(key);
          return (
            <li key={key}>
              <Link href={adminPagePath(key)}
                    className="group flex h-full flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 transition-all hover:-translate-y-0.5 hover:border-[var(--primary)] hover:shadow-md">
                <span className="flex items-center justify-between gap-3">
                  <span className="font-display text-xl font-semibold group-hover:text-[var(--heading)]">{spec.title}</span>
                  <span className="font-mono text-xs text-[var(--muted)]">{spec.path}</span>
                </span>
                <span className="mt-2 text-sm text-[var(--muted)]">{spec.description}</span>
                <span className="mt-auto pt-5 text-xs">
                  {when
                    ? <span className="font-medium">● Edited {dateFormat.format(new Date(when))} UTC</span>
                    : <span className="text-[var(--muted)]">○ Original wording</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
