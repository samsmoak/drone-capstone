import Link from "next/link";
import { AgentStatus } from "@/components/ui/agent-status";
import { DownloadButtons } from "@/components/ui/download-buttons";
import { getPageContent } from "@/lib/queries";
import { HARDWARE } from "@/lib/routes";
import { flag, items, strings, text } from "@/lib/site-content";

export const metadata = {
  title: "Set up the system",
  description:
    "Get CropWatcher flying: what you need, installing the app, positioning setup, your " +
    "first flight, and what to do when it will not take off.",
};

/** Every word here is edited at /admin/pages/setup. */
export default async function SetupPage() {
  const setup = await getPageContent("setup");

  return (
    <main className="mx-auto max-w-3xl px-6 py-14">
      <h1 className="font-display text-4xl font-semibold tracking-tight">{text(setup, "title")}</h1>
      <p className="mt-3 text-lg text-[var(--muted)]">{text(setup, "intro")}</p>

      <div className="mt-8"><AgentStatus /></div>

      <ol className="mt-12 space-y-10">
        {items(setup, "steps").map((step, i) => {
          const bullets = strings(step, "bullets");
          const note = text(step, "note");
          return (
            <li key={`${text(step, "title")}-${i}`} className="flex gap-5">
              <span aria-hidden="true"
                    className="tabular flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-sm font-semibold">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="text-lg font-medium">{text(step, "title")}</h2>
                <div className="mt-2 space-y-3">
                  {strings(step, "paragraphs").map((para, j) => (
                    <p key={j} className="text-[var(--muted)]">{para}</p>
                  ))}
                  {bullets.length > 0 && (
                    <ul className="space-y-1.5 text-sm">
                      {bullets.map((item, j) => (
                        <li key={j} className="flex gap-2">
                          <span aria-hidden="true" className="text-[var(--muted)]">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {flag(step, "showDownloads") && <DownloadButtons />}
                  {note && (
                    <p className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm">{note}</p>
                  )}
                  {flag(step, "linkHardware") && (
                    <p className="text-sm text-[var(--muted)]">
                      Not sure which part is which?{" "}
                      <Link href={HARDWARE} className="underline underline-offset-4">
                        See every component photographed and labelled
                      </Link>.
                    </p>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <section className="mt-16 border-t border-[var(--border)] pt-10">
        <h2 className="font-display text-2xl font-semibold tracking-tight">{text(setup, "troubleTitle")}</h2>
        <p className="mt-2 text-[var(--muted)]">{text(setup, "troubleIntro")}</p>
        <div className="mt-6 space-y-4">
          {items(setup, "troubles").map((item, i) => (
            <details key={`${text(item, "symptom")}-${i}`} className="group rounded-lg border border-[var(--border)] bg-[var(--surface)]">
              <summary className="flex min-h-11 cursor-pointer items-center px-4 py-3 font-medium">
                {text(item, "symptom")}
              </summary>
              <div className="border-t border-[var(--border)] px-4 py-3">
                <p className="text-sm"><span className="text-[var(--muted)]">Usually: </span>{text(item, "cause")}</p>
                <p className="mt-2 text-sm text-[var(--muted)]">{text(item, "fix")}</p>
              </div>
            </details>
          ))}
        </div>
      </section>
    </main>
  );
}
