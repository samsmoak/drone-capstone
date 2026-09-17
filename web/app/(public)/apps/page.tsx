import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "@/components/site/PageIntro";
import {
  APPS, bundleFile, formatBytes, formatDate, manifest, type AppBundle,
} from "@/lib/installers";
import { getPageContent } from "@/lib/queries";
import { SETUP } from "@/lib/routes";
import { text } from "@/lib/site-content";

export const metadata: Metadata = {
  title: "Apps",
  description:
    "Download the CropWatcher desktop app for macOS or Windows. Built by CI from the main " +
    "branch, so the download is never behind the code.",
};

function AppleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5 shrink-0" aria-hidden="true">
      <path d="M17.05 12.94c-.03-2.7 2.2-3.99 2.3-4.06-1.25-1.83-3.2-2.08-3.9-2.11-1.66-.17-3.24.98-4.08.98-.84 0-2.14-.96-3.52-.93-1.81.03-3.48 1.05-4.41 2.67-1.88 3.26-.48 8.08 1.35 10.72.9 1.29 1.97 2.74 3.38 2.69 1.36-.06 1.87-.88 3.51-.88 1.64 0 2.1.88 3.53.85 1.46-.02 2.38-1.31 3.27-2.61 1.03-1.5 1.46-2.95 1.48-3.03-.03-.01-2.84-1.09-2.87-4.29zM14.4 4.9c.74-.9 1.24-2.15 1.1-3.4-1.07.05-2.36.72-3.13 1.61-.68.79-1.28 2.06-1.12 3.28 1.19.09 2.41-.6 3.15-1.49z" />
    </svg>
  );
}

function WindowsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5 shrink-0" aria-hidden="true">
      <path d="M3 5.6 10.2 4.6v6.9H3V5.6zm0 12.8 7.2 1v-6.8H3v5.8zM11.2 4.4 21 3v8.5h-9.8V4.4zm0 8.1H21V21l-9.8-1.4v-7.1z" />
    </svg>
  );
}

/** One app: what it is, then a card per platform. */
async function AppSection({ app, version }: { app: AppBundle; version: string | null }) {
  const platforms = await Promise.all(
    app.platforms.map(async (platform) => ({ ...platform, file: await bundleFile(platform.object) })),
  );
  const anyPublished = platforms.some((p) => p.file.url);

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 sm:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-display text-2xl font-semibold tracking-tight">{app.name}</h2>
          <p className="mt-2 max-w-2xl leading-relaxed text-[var(--muted)]">{app.summary}</p>
        </div>
        {version && (
          <span className="tabular rounded-full border border-[var(--border)] px-3 py-1 text-xs font-semibold">
            Version {version}
          </span>
        )}
      </div>

      <ul className="mt-5 grid gap-2">
        {app.points.map((point) => (
          <li key={point} className="flex gap-2.5 text-sm leading-relaxed">
            <span aria-hidden="true" className="text-[var(--heading)]">▸</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>

      <div className="mt-7 grid gap-4 sm:grid-cols-2">
        {platforms.map((platform) => {
          const size = formatBytes(platform.file.bytes);
          const built = formatDate(platform.file.updated);
          return (
            <article
              key={platform.object}
              className="flex flex-col rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5"
            >
              <h3 className="font-display flex items-center gap-2.5 text-lg font-semibold">
                {platform.os === "macOS" ? <AppleIcon /> : <WindowsIcon />}
                {platform.os}
              </h3>
              <p className="mt-1.5 text-sm text-[var(--muted)]">{platform.note}</p>

              <div className="mt-4">
                {platform.file.url ? (
                  <a
                    href={platform.file.url}
                    download
                    className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--primary)] px-5 text-sm font-medium text-[var(--on-primary)]"
                  >
                    Download{size ? ` · ${size}` : ""}
                  </a>
                ) : (
                  <span className="inline-flex min-h-11 items-center rounded-lg border border-dashed border-[var(--border)] px-5 text-sm text-[var(--muted)]">
                    Coming soon — the first build has not finished yet
                  </span>
                )}
              </div>

              {built && <p className="tabular mt-3 text-xs text-[var(--muted)]">Built {built}</p>}
              <p className="mt-3 text-xs leading-relaxed text-[var(--muted)]">{platform.unsigned}</p>
            </article>
          );
        })}
      </div>

      {!anyPublished && (
        <p className="mt-5 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-4 text-sm text-[var(--muted)]">
          No build has been published yet. One is produced automatically whenever the app
          changes on the main branch, and appears here without anyone redeploying this site.
        </p>
      )}
    </section>
  );
}

/** Every word of the wording here is edited at /admin/pages/apps. */
export default async function AppsPage() {
  const [content, build] = await Promise.all([getPageContent("apps"), manifest()]);
  const built = formatDate(build?.built_at ?? null);

  return (
    <main className={`${SITE_CONTAINER} py-14`}>
      <PageIntro content={content} />

      {text(content, "note") && (
        <p className={`${PROSE_COLUMN} mt-8 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 leading-relaxed`}>
          {text(content, "note")}
        </p>
      )}

      {(build?.version || built || build?.commit) && (
        <p className="tabular mt-6 text-sm text-[var(--muted)]">
          {[
            build?.version && `Current version ${build.version}`,
            built && `built ${built}`,
            build?.commit && `commit ${build.commit.slice(0, 7)}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}

      <div className="mt-8 grid gap-6">
        {APPS.map((app) => (
          <AppSection key={app.key} app={app} version={build?.version ?? null} />
        ))}
      </div>

      <section className={`${PROSE_COLUMN} mt-12 border-t border-[var(--border)] pt-8`}>
        <h2 className="font-display text-xl font-semibold tracking-tight">
          {text(content, "unsignedTitle")}
        </h2>
        <p className="mt-3 leading-relaxed text-[var(--muted)]">{text(content, "unsignedIntro")}</p>
        <p className="mt-4 text-sm text-[var(--muted)]">
          Installed it already?{" "}
          <Link href={SETUP} className="underline underline-offset-4">
            The setup guide takes it from there
          </Link>
          .
        </p>
      </section>
    </main>
  );
}
