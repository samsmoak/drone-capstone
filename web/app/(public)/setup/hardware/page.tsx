import Image from "next/image";

export const metadata = {
  title: "Hardware",
  description:
    "Every component of the CropWatcher kit, photographed and labelled — " +
    "including where the sensors actually are.",
};

const PARTS = [
  {
    photo: "02-crazyflie-2.1-mainboard-top-flat.jpeg",
    alt: "Crazyflie 2.1 mainboard seen from above, propellers fitted",
    name: "Crazyflie 2.1 — the drone",
    body:
      "The whole aircraft. Look for the ON/OFF button, the micro-USB port, and " +
      "the M1–M4 motor labels. The white two-pin plug is where the battery goes.",
  },
  {
    photo: "05-crazyradio-pa-usb-dongle.jpeg",
    alt: "Crazyradio PA USB dongle with its screw-on antenna",
    name: "Crazyradio PA — the radio link",
    body:
      "This plugs into your laptop, not the drone. It is how the two talk. " +
      "USB-A, so a USB-C laptop needs an adapter. No driver to install.",
  },
  {
    photo: "06-lipo-batteries-x2-and-usb-charger.jpeg",
    alt: "Two LiPo battery packs and a small USB charger board",
    name: "Batteries and charger",
    body:
      "Two 240 mAh packs and the micro-USB charger board. A full pack gives " +
      "roughly four minutes of flight. They ship part-charged, so charge before " +
      "your first session.",
  },
  {
    photo: "03-ai-deck-1.1-mounted-underside-a.jpeg",
    alt: "AI deck mounted under the drone, camera module visible at the left edge",
    name: "AI deck — camera (optional)",
    body:
      "The black module at the left edge is the camera. It is the one part that " +
      "never reached a working state: its Wi-Fi datalink was cut from the " +
      "original project, and nothing here depends on it.",
  },
  {
    photo: "07-cf-battery-holder-and-pin-headers.jpeg",
    alt: "Battery holder circuit board beside two strips of pin headers",
    name: "Battery holder and headers",
    body:
      "The frame that clamps the battery to the drone, plus the long pin headers " +
      "used to stack expansion decks above the mainboard.",
  },
  {
    photo: "08-spare-motor-mounts-x2.jpeg",
    alt: "Two clear plastic motor mounts",
    name: "Spare motor mounts",
    body:
      "The clear plastic clips that hold a motor at the end of each arm. Replace " +
      "a cracked one before flying — small cracks cause vibration.",
  },
  {
    photo: "09-spare-coreless-motor-a.jpeg",
    alt: "A single small coreless motor with its connector lead",
    name: "Spare motor",
    body: "One replacement coreless motor, ready to plug in.",
  },
];

export default function HardwarePage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-14">
      <h1 className="text-3xl font-semibold tracking-tight">Hardware</h1>
      <p className="mt-3 text-lg text-[var(--muted)]">
        Every part of the kit, photographed. If you are trying to work out which
        thing is which, this is the page.
      </p>

      <section className="mt-10 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-5">
        <h2 className="font-medium">Where are the sensors?</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">
          This is the most common question, and the answer surprises people:{" "}
          <strong className="text-[var(--foreground)]">
            you cannot see most of them
          </strong>
          . The temperature and pressure sensor and the motion sensors are chips
          two or three millimetres across, soldered onto the mainboard. There is
          no separate &ldquo;sensor module&rdquo; to find. The only sensor you can
          point at is the camera on the AI deck.
        </p>
        <p className="mt-2 text-sm text-[var(--muted)]">
          The Lighthouse positioning deck — a small board with four black domes —
          is the one part that is genuinely easy to miss, and nothing can hold a
          position without it.
        </p>
      </section>

      <div className="mt-12 space-y-12">
        {PARTS.map((part) => (
          <article key={part.photo}>
            <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-2)]">
              <Image
                src={`/hardware/${part.photo}`}
                alt={part.alt}
                width={1600}
                height={1200}
                className="h-auto w-full"
                sizes="(max-width: 768px) 100vw, 768px"
              />
            </div>
            <h2 className="mt-4 text-lg font-medium">{part.name}</h2>
            <p className="mt-1 text-[var(--muted)]">{part.body}</p>
          </article>
        ))}
      </div>
    </main>
  );
}
