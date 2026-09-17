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
    <main className="mx-auto max-w-3xl px-6 py-14">
      <h1 className="font-display text-4xl font-semibold tracking-tight">{text(hardware, "title")}</h1>
      <p className="mt-3 text-lg text-[var(--muted)]">{text(hardware, "intro")}</p>

      <section className="mt-10 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5">
        <h2 className="font-medium">{text(hardware, "sensorsTitle")}</h2>
        {strings(hardware, "sensorsParagraphs").map((para, i) => (
          <p key={i} className="mt-2 text-sm text-[var(--muted)]">{para}</p>
        ))}
      </section>

      <div className="mt-12 space-y-12">
        {items(hardware, "parts").map((part, i) => {
          const image = text(part, "image");
          return (
            <article key={`${text(part, "name")}-${i}`}>
              {image && (
                <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-2)]">
                  <Image src={image} alt={text(part, "alt")} width={1600} height={1200}
                         className="h-auto w-full" sizes="(max-width: 768px) 100vw, 768px" />
                </div>
              )}
              <h2 className="mt-4 text-lg font-medium">{text(part, "name")}</h2>
              <p className="mt-1 text-[var(--muted)]">{text(part, "body")}</p>
            </article>
          );
        })}
      </div>
    </main>
  );
}
