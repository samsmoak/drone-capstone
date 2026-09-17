/**
 * The wording of every public page, editable from /admin/pages.
 *
 * Each page is described once here: a field spec (what can be edited, and how
 * the admin form draws it) and its default wording (what the page said before it
 * was editable, copied verbatim). The database stores only overrides
 * (`site_pages`, migration 0009):
 *
 *   - a page with no row shows its defaults, so nothing can blank for want of a row
 *   - everything read or saved goes through `normalizeContent`, which keeps only
 *     the fields the spec declares, of the declared type — a malformed row or a
 *     crafted request cannot put anything else on a public page
 *
 * Shared by the server (pages, mutations) and the client (the admin form), so it
 * imports nothing server-only.
 */

export type FieldSpec =
  | { type: "text"; key: string; label: string; hint?: string }
  | { type: "textarea"; key: string; label: string; hint?: string }
  | { type: "boolean"; key: string; label: string; hint?: string }
  | { type: "image"; key: string; label: string; hint?: string }
  | { type: "strings"; key: string; label: string; itemLabel: string; hint?: string }
  | { type: "items"; key: string; label: string; itemLabel: string; fields: FieldSpec[]; hint?: string };

export type PageSpec = {
  key: PageKey;
  title: string;
  description: string;
  path: string;
  fields: FieldSpec[];
};

export type ContentValue = string | boolean | string[] | ContentObject[];
export type ContentObject = { [key: string]: ContentValue };

// ── defaults: the wording the pages shipped with ─────────────────────────

const HEADER_FIELDS: FieldSpec[] = [
  { type: "text", key: "eyebrow", label: "Small label above the title" },
  { type: "text", key: "title", label: "Title" },
  { type: "textarea", key: "intro", label: "Introduction" },
];

export const PAGE_SPECS = {
  site: {
    key: "site",
    title: "Whole site",
    description: "The footer shown on every visitor page.",
    path: "/",
    fields: [
      { type: "textarea", key: "footerText", label: "Footer text" },
      { type: "text", key: "footerLinkLabel", label: "Footer link label", hint: "Links to the Set Up page." },
    ],
  },
  home: {
    key: "home",
    title: "Home",
    description: "The landing page every visitor sees first.",
    path: "/",
    fields: [
      ...HEADER_FIELDS,
      { type: "text", key: "primaryCta", label: "Main button", hint: "Goes to Projects." },
      { type: "text", key: "secondaryCta", label: "Second button", hint: "Goes to the dashboard (sign-in first)." },
      { type: "image", key: "heroImage", label: "Main photo", hint: "Beside the title. Leave empty for none." },
      { type: "text", key: "heroImageAlt", label: "Main photo description", hint: "Read aloud by screen readers." },
      {
        type: "items", key: "capabilities", label: "Capability cards", itemLabel: "Card",
        fields: [
          { type: "image", key: "image", label: "Photo", hint: "Optional. Sits above the title." },
          { type: "text", key: "title", label: "Title" },
          { type: "textarea", key: "body", label: "Text" },
        ],
      },
      { type: "boolean", key: "showGallery", label: "Show a strip of photos from the gallery" },
      { type: "text", key: "galleryTitle", label: "Title of the photo strip" },
      { type: "text", key: "teamLine", label: "Line above the footer" },
      { type: "text", key: "teamLinkLabel", label: "Team link label" },
    ],
  },
  projects: {
    key: "projects", title: "Projects", description: "The heading of the projects list.",
    path: "/projects", fields: HEADER_FIELDS,
  },
  team: {
    key: "team", title: "Team", description: "The heading of the team page.",
    path: "/team", fields: HEADER_FIELDS,
  },
  gallery: {
    key: "gallery", title: "Gallery", description: "The heading of the gallery.",
    path: "/gallery", fields: HEADER_FIELDS,
  },
  apps: {
    key: "apps",
    title: "Apps",
    description: "The download page. The builds themselves come from CI, not from here.",
    path: "/apps",
    fields: [
      ...HEADER_FIELDS,
      { type: "textarea", key: "note", label: "Note above the downloads", hint: "Shown in a shaded box." },
      { type: "text", key: "unsignedTitle", label: "Heading of the 'it will warn you' section" },
      { type: "textarea", key: "unsignedIntro", label: "Text of that section" },
    ],
  },
  setup: {
    key: "setup",
    title: "Set Up",
    description: "From an unopened box to a first flight, and what to do when it will not fly.",
    path: "/setup",
    fields: [
      { type: "text", key: "title", label: "Title" },
      { type: "textarea", key: "intro", label: "Introduction" },
      {
        type: "items", key: "steps", label: "Steps", itemLabel: "Step",
        fields: [
          { type: "text", key: "title", label: "Step title" },
          { type: "strings", key: "paragraphs", label: "Paragraphs", itemLabel: "Paragraph" },
          { type: "strings", key: "bullets", label: "Bullet points", itemLabel: "Bullet" },
          { type: "textarea", key: "note", label: "Highlighted note", hint: "Shown in a shaded box. Leave empty for none." },
          { type: "boolean", key: "showDownloads", label: "Show the app download buttons" },
          { type: "boolean", key: "linkHardware", label: "Link to the Hardware page" },
        ],
      },
      { type: "text", key: "troubleTitle", label: "Troubleshooting title" },
      { type: "textarea", key: "troubleIntro", label: "Troubleshooting introduction" },
      {
        type: "items", key: "troubles", label: "Problems", itemLabel: "Problem",
        fields: [
          { type: "text", key: "symptom", label: "What you see" },
          { type: "text", key: "cause", label: "Usual cause" },
          { type: "textarea", key: "fix", label: "What to do" },
        ],
      },
    ],
  },
  hardware: {
    key: "hardware",
    title: "Hardware",
    description: "Every part of the kit, photographed and labelled.",
    path: "/setup/hardware",
    fields: [
      { type: "text", key: "title", label: "Title" },
      { type: "textarea", key: "intro", label: "Introduction" },
      { type: "text", key: "sensorsTitle", label: "Highlighted section title" },
      { type: "strings", key: "sensorsParagraphs", label: "Highlighted section paragraphs", itemLabel: "Paragraph" },
      {
        type: "items", key: "parts", label: "Parts", itemLabel: "Part",
        fields: [
          { type: "image", key: "image", label: "Photo" },
          { type: "text", key: "alt", label: "Photo description", hint: "Read aloud by screen readers." },
          { type: "text", key: "name", label: "Name" },
          { type: "textarea", key: "body", label: "Description" },
        ],
      },
    ],
  },
} satisfies Record<string, PageSpec>;

export type PageKey = "site" | "home" | "projects" | "team" | "gallery" | "apps" | "setup" | "hardware";
export const PAGE_KEYS = Object.keys(PAGE_SPECS) as PageKey[];

export function isPageKey(value: string): value is PageKey {
  return (PAGE_KEYS as string[]).includes(value);
}

export const PAGE_DEFAULTS: Record<PageKey, ContentObject> = {
  site: {
    footerText: "CropWatcher — capstone project. Built on a Crazyflie 2.1.",
    footerLinkLabel: "Set up the system",
  },
  home: {
    eyebrow: "Capstone project",
    title: "CropWatcher",
    intro:
      "An autonomous indoor scouting drone that flies a greenhouse, records position-tagged " +
      "environmental data, and turns it into a crop-health map.",
    primaryCta: "See the projects",
    secondaryCta: "Dashboard",
    heroImage: "/home/hero-greenhouse.jpg",
    heroImageAlt: "Rows of crops growing under a greenhouse roof",
    showGallery: true,
    galleryTitle: "From the gallery",
    capabilities: [
      {
        image: "/home/autonomous-flight.jpg",
        title: "Autonomous flight",
        body:
          "Lawnmower scans and custom waypoint routes, flown under closed-loop position " +
          "control with Lighthouse indoor positioning.",
      },
      {
        image: "/home/sensing.jpg",
        title: "Corrected sensing",
        body:
          "The barometer sits on a board that heats itself. A two-timescale thermal model " +
          "separates the electronics from the room, validated to 0.12 °F.",
      },
      {
        image: "/home/safety.jpg",
        title: "Safety before arming",
        body:
          "Every plan is checked against a geofence and an obstacle map before a motor " +
          "spins — including the leg out of the takeoff point.",
      },
      {
        image: "/home/zones.jpg",
        title: "Zone-level health",
        body:
          "Position-tagged readings become a greenhouse map, so a grower can see which rows " +
          "need attention rather than reading a spreadsheet.",
      },
    ],
    teamLine: "Built on a Crazyflie 2.1 with Lighthouse positioning.",
    teamLinkLabel: "Meet the team",
  },
  projects: {
    eyebrow: "Portfolio",
    title: "Projects",
    intro:
      "The pieces that make CropWatcher fly, sense and stay safe — each written up by the " +
      "people who built it.",
  },
  team: {
    eyebrow: "Capstone team",
    title: "The team",
    intro: "The people who designed, built and flew CropWatcher.",
  },
  gallery: {
    eyebrow: "Gallery",
    title: "The kit, the team, and the drone in the air",
    intro: "Photos and videos from building and flying CropWatcher, grouped into albums.",
  },
  apps: {
    eyebrow: "Downloads",
    title: "Get the apps",
    intro:
      "Everything you need to run CropWatcher on your own machine. Each build is produced by " +
      "CI from the code on the main branch, so what is here is what the project is.",
    note:
      "The desktop app has to run on the computer with the Crazyradio plugged in — the radio " +
      "is a USB dongle, so no website can command the drone.",
    unsignedTitle: "Your computer will warn you",
    unsignedIntro:
      "These builds are not code-signed: a capstone project has no Apple or Microsoft " +
      "developer certificate. The warning is about the certificate, not about the file.",
  },
  setup: {
    title: "Set up the system",
    intro: "From an unopened box to a first flight. About 30 minutes, most of it waiting for a battery.",
    steps: [
      {
        title: "Check you have everything",
        paragraphs: ["Six things. Miss one and the drone either will not fly or will not know where it is."],
        bullets: [
          "Crazyflie 2.1 drone, assembled with propellers fitted",
          "Lighthouse positioning deck — a small board with four black domes",
          "Two Lighthouse V2 base stations",
          "Crazyradio PA — the USB dongle with the antenna",
          "At least one charged LiPo battery",
          "A USB-C to micro-USB cable, for charging",
        ],
        note: "",
        showDownloads: false,
        linkHardware: true,
      },
      {
        title: "Install the CropWatcher app",
        paragraphs: ["One download. It contains everything — you will not need Python, a terminal, or any commands."],
        bullets: [],
        note:
          "On a Mac, the first launch will say the app is from an unidentified developer. That " +
          "is expected. Right-click the app and choose Open, then confirm. You only do this once.",
        showDownloads: true,
        linkHardware: false,
      },
      {
        title: "Plug in the radio",
        paragraphs: [
          "The Crazyradio goes into your laptop, not the drone. It is a USB-A plug, so most " +
          "modern Macs need a USB-C adapter or a hub. No driver to install — the app finds it.",
        ],
        bullets: [],
        note: "",
        showDownloads: false,
        linkHardware: false,
      },
      {
        title: "Set up positioning",
        paragraphs: [
          "The drone cannot hold a position without this. Two base stations, in opposite corners " +
          "of the flight area, about two metres up, both angled toward the middle.",
          "Then run geometry calibration once: place the drone where you want the origin, keep " +
          "it still, and start the estimate. Repeat this any time a base station is moved or knocked.",
        ],
        bullets: [],
        note: "",
        showDownloads: false,
        linkHardware: false,
      },
      {
        title: "Check before you fly",
        paragraphs: ["Press Check in the app. Nothing spins — it asks the drone four questions and shows the answers:"],
        bullets: [
          "Is the battery charged enough to arm?",
          "Is the positioning deck fitted?",
          "Can it see the base stations?",
          "Has its position estimate settled?",
        ],
        note: "All four green means you are ready. Anything else tells you exactly what to fix.",
        showDownloads: false,
        linkHardware: false,
      },
      {
        title: "Your first flight",
        paragraphs: [
          "Start small: 30 cm for a few seconds. Put the drone on the floor, not a table, with " +
          "about two metres clear around it and nothing fragile nearby.",
          "It will take off, hold its height, and land by itself. Once that works, scale up.",
        ],
        bullets: [],
        note: "",
        showDownloads: false,
        linkHardware: false,
      },
    ],
    troubleTitle: "When it will not fly",
    troubleIntro:
      "Every one of these cost us real time during bring-up. Symptoms first, because that is " +
      "what you actually see.",
    troubles: [
      {
        symptom: "I press fly and absolutely nothing happens",
        cause: "The battery is too low for the drone to arm.",
        fix:
          "The drone refuses to spin its motors below about 3.75 V, and it will not tell you out " +
          "loud. Charge for 20–30 minutes, then power-cycle the drone. The Check screen shows this " +
          "as 'firmware will not arm'.",
      },
      {
        symptom: "The app says no drone found",
        cause: "The radio or the drone is not visible.",
        fix:
          "Confirm the dongle is plugged in — with an adapter if your laptop is USB-C only. Then " +
          "confirm the battery is connected and the drone is switched on. LEDs lighting up does " +
          "not mean the battery is charged.",
      },
      {
        symptom: "It lifts a few centimetres and will not go higher",
        cause: "It has no position feedback, so it cannot climb safely.",
        fix:
          "Check the Lighthouse deck is fitted and both base stations are powered and visible. If " +
          "the Check screen shows zero base stations, something is blocking the line of sight.",
      },
      {
        symptom: "It drifts around instead of holding still",
        cause: "The position estimate is unstable where the drone is sitting.",
        fix:
          "Move it back toward the middle of the flight area and try again. If it keeps drifting, " +
          "re-run geometry calibration — a base station has probably been moved.",
      },
      {
        symptom: "It flew, then landed on its own part-way through",
        cause: "The battery dropped to the safety threshold.",
        fix:
          "This is the system working. It lands under control rather than cutting out mid-air. " +
          "Charge fully before a long mission — a full pack gives roughly four minutes of flight.",
      },
      {
        symptom: "Manual control will not connect",
        cause: "The browser cannot reach the app on your machine.",
        fix:
          "Manual flight needs the CropWatcher app running on the same computer or the same " +
          "network. It deliberately does not work over the internet: the delay would make the " +
          "drone unflyable.",
      },
    ],
  },
  hardware: {
    title: "Hardware",
    intro:
      "Every part of the kit, photographed. If you are trying to work out which thing is which, " +
      "this is the page.",
    sensorsTitle: "Where are the sensors?",
    sensorsParagraphs: [
      "This is the most common question, and the answer surprises people: you cannot see most of " +
      "them. The temperature and pressure sensor and the motion sensors are chips two or three " +
      "millimetres across, soldered onto the mainboard. There is no separate “sensor module” to " +
      "find. The only sensor you can point at is the camera on the AI deck.",
      "The Lighthouse positioning deck — a small board with four black domes — is the one part " +
      "that is genuinely easy to miss, and nothing can hold a position without it.",
    ],
    parts: [
      {
        image: "/hardware/02-crazyflie-2.1-mainboard-top-flat.jpeg",
        alt: "Crazyflie 2.1 mainboard seen from above, propellers fitted",
        name: "Crazyflie 2.1 — the drone",
        body:
          "The whole aircraft. Look for the ON/OFF button, the micro-USB port, and the M1–M4 motor " +
          "labels. The white two-pin plug is where the battery goes.",
      },
      {
        image: "/hardware/05-crazyradio-pa-usb-dongle.jpeg",
        alt: "Crazyradio PA USB dongle with its screw-on antenna",
        name: "Crazyradio PA — the radio link",
        body:
          "This plugs into your laptop, not the drone. It is how the two talk. USB-A, so a USB-C " +
          "laptop needs an adapter. No driver to install.",
      },
      {
        image: "/hardware/06-lipo-batteries-x2-and-usb-charger.jpeg",
        alt: "Two LiPo battery packs and a small USB charger board",
        name: "Batteries and charger",
        body:
          "Two 240 mAh packs and the micro-USB charger board. A full pack gives roughly four " +
          "minutes of flight. They ship part-charged, so charge before your first session.",
      },
      {
        image: "/hardware/03-ai-deck-1.1-mounted-underside-a.jpeg",
        alt: "AI deck mounted under the drone, camera module visible at the left edge",
        name: "AI deck — camera (optional)",
        body:
          "The black module at the left edge is the camera. It is the one part that never reached " +
          "a working state: its Wi-Fi datalink was cut from the original project, and nothing here " +
          "depends on it.",
      },
      {
        image: "/hardware/07-cf-battery-holder-and-pin-headers.jpeg",
        alt: "Battery holder circuit board beside two strips of pin headers",
        name: "Battery holder and headers",
        body:
          "The frame that clamps the battery to the drone, plus the long pin headers used to stack " +
          "expansion decks above the mainboard.",
      },
      {
        image: "/hardware/08-spare-motor-mounts-x2.jpeg",
        alt: "Two clear plastic motor mounts",
        name: "Spare motor mounts",
        body:
          "The clear plastic clips that hold a motor at the end of each arm. Replace a cracked one " +
          "before flying — small cracks cause vibration.",
      },
      {
        image: "/hardware/09-spare-coreless-motor-a.jpeg",
        alt: "A single small coreless motor with its connector lead",
        name: "Spare motor",
        body: "One replacement coreless motor, ready to plug in.",
      },
    ],
  },
};

// ── normalising ──────────────────────────────────────────────────────────

const MAX_TEXT = 5000;
const MAX_LIST = 60;

function emptyValue(field: FieldSpec): ContentValue {
  switch (field.type) {
    case "boolean": return false;
    case "strings":
    case "items": return [];
    default: return "";
  }
}

/** An empty item for an `items` list — what the admin's "Add" button creates. */
export function emptyItem(fields: FieldSpec[]): ContentObject {
  return Object.fromEntries(fields.map((f) => [f.key, emptyValue(f)]));
}

function normalizeField(field: FieldSpec, value: unknown, fallback: ContentValue | undefined): ContentValue {
  const safeFallback = fallback ?? emptyValue(field);
  switch (field.type) {
    case "text":
    case "textarea":
      return typeof value === "string" ? value.slice(0, MAX_TEXT) : safeFallback;
    case "image":
      // A site-relative path or an https URL; anything else (javascript:, data:)
      // is refused rather than rendered.
      return typeof value === "string" && (value === "" || /^(\/(?!\/)|https:\/\/)/.test(value))
        ? value.slice(0, MAX_TEXT)
        : safeFallback;
    case "boolean":
      return typeof value === "boolean" ? value : safeFallback;
    case "strings":
      return Array.isArray(value)
        ? value.filter((v): v is string => typeof v === "string").slice(0, MAX_LIST).map((v) => v.slice(0, MAX_TEXT))
        : safeFallback;
    case "items": {
      if (!Array.isArray(value)) return safeFallback;
      return value
        .filter((v): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v))
        .slice(0, MAX_LIST)
        .map((item) => normalizeObject(field.fields, item, emptyItem(field.fields)));
    }
  }
}

function normalizeObject(fields: FieldSpec[], value: Record<string, unknown>, defaults: ContentObject): ContentObject {
  return Object.fromEntries(fields.map((f) => [f.key, normalizeField(f, value[f.key], defaults[f.key])]));
}

/**
 * The page's content: stored values where they are valid, defaults where a
 * field is missing or the wrong type. Unknown keys are dropped.
 */
export function normalizeContent(key: PageKey, stored: unknown): ContentObject {
  const spec = PAGE_SPECS[key];
  const raw = typeof stored === "object" && stored !== null && !Array.isArray(stored)
    ? (stored as Record<string, unknown>)
    : {};
  return normalizeObject(spec.fields, raw, PAGE_DEFAULTS[key]);
}

// ── typed accessors for the pages ────────────────────────────────────────

export const text = (content: ContentObject, key: string): string =>
  typeof content[key] === "string" ? (content[key] as string) : "";

export const flag = (content: ContentObject, key: string): boolean => content[key] === true;

export const strings = (content: ContentObject, key: string): string[] =>
  Array.isArray(content[key]) ? (content[key] as unknown[]).filter((v): v is string => typeof v === "string") : [];

export const items = (content: ContentObject, key: string): ContentObject[] =>
  Array.isArray(content[key])
    ? (content[key] as unknown[]).filter((v): v is ContentObject => typeof v === "object" && v !== null)
    : [];
