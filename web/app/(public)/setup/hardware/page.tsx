import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import Image from "next/image";
import { getPageContent } from "@/lib/queries";
import { items, strings, text } from "@/lib/site-content";

export const metadata = {
  title: "Hardware",
  description:
    "Every component of the CropWatcher kit, photographed and labelled — including where " +
    "the sensors actually are.",
};

/** Every word and photo here is edited at /admin/pages/hardware. */
export default async function HardwarePage() {
  const hardware = await getPageContent("hardware");

  return (
    <main className={`${SITE_CONTAINER} py-14`}>
      <header className={PROSE_COLUMN}>
        <h1 className="font-display text-4xl font-semibold tracking-tight">{text(hardware, "title")}</h1>
        <p className="mt-3 text-lg text-[var(--muted)]">{text(hardware, "intro")}</p>
      </header>

      <section className="mt-10 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-6 sm:p-8">
        <h2 className="font-display text-xl font-semibold">{text(hardware, "sensorsTitle")}</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2 md:gap-8">
          {strings(hardware, "sensorsParagraphs").map((para, i) => (
            <p key={i} className="text-sm leading-relaxed text-[var(--muted)]">{para}</p>
          ))}
        </div>
      </section>

      {/* Two parts to a row on a wide screen, one on a phone. */}
      <div className="mt-12 grid gap-x-10 gap-y-12 md:grid-cols-2">
        {items(hardware, "parts").map((part, i) => {
          const image = text(part, "image");
          return (
            <article key={`${text(part, "name")}-${i}`}>
              {image && (
                <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-2)]">
                  <Image src={image} alt={text(part, "alt")} width={1600} height={1200}
                         className="h-auto w-full" sizes="(max-width: 768px) 100vw, 45vw" />
                </div>
              )}
              <h2 className="mt-4 text-lg font-medium">{text(part, "name")}</h2>
              <p className="mt-1 leading-relaxed text-[var(--muted)]">{text(part, "body")}</p>
            </article>
          );
        })}
      </div>
    </main>
  );
}
