#!/usr/bin/env node
// Install CropWatcher from a terminal, on macOS or Windows, in one command:
//
//   git clone https://github.com/samsmoak/drone-capstone.git
//   cd drone-capstone
//   node scripts/install.mjs
//
// It runs three things, and stops at the first that fails, saying why:
//   1. scripts/setup.mjs — checks the toolchain (every problem listed at once,
//      each with its fix) and installs the agent and the app's packages;
//   2. the build — the flight agent is frozen and verified first, then only
//      the bundle this OS installs from (.app on macOS, the installer on
//      Windows; the .dmg is skipped: it needs Finder, and nothing here uses it);
//   3. the install — macOS copies the app into /Applications (~/Applications
//      if that is not writable); Windows runs the installer silently, for
//      this user only, so no administrator prompt.
//
// Running it again updates the installed app in place.
//
//   --open         open the app when it is installed
//   --no-install   build only; leave the installed app alone
//   --dev          also install the agent's test tools (passed to setup)
//
// There is no downloadable installer to fetch: every machine builds its own,
// which is also what makes an Intel Mac and an Apple-silicon Mac each get the
// right one (PyInstaller freezes for the CPU of the machine it runs on).
//
// CROPWATCHER_INSTALL_DIR (macOS) installs somewhere else — for testing.

import { spawnSync } from "node:child_process";
import { accessSync, constants, existsSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DESKTOP = join(ROOT, "desktop");
const RELEASE = join(DESKTOP, "src-tauri", "target", "release");
const WINDOWS = process.platform === "win32";
const MAC = process.platform === "darwin";
const APP = "CropWatcher";

const USAGE = "usage: node scripts/install.mjs [--open] [--no-install] [--dev]";
const flags = process.argv.slice(2);
for (const flag of flags) {
  if (!["--open", "--no-install", "--dev"].includes(flag)) {
    console.error(`unknown option ${flag}\n${USAGE}`);
    process.exit(2);
  }
}
const OPEN = flags.includes("--open");
const INSTALL = !flags.includes("--no-install") && (MAC || WINDOWS);
const version = JSON.parse(readFileSync(join(DESKTOP, "src-tauri", "tauri.conf.json"), "utf8")).version;

function fail(message) {
  console.error(`\n  ${message}\n`);
  process.exit(1);
}

/** Run a step the user should watch. Exits with a clear line if it fails. */
function step(label, command, args, { cwd = ROOT, shell = false, env } = {}) {
  console.log(`\n==> ${label}`);
  const result = spawnSync(command, args, {
    cwd, shell, stdio: "inherit", windowsHide: true, env: env ?? process.env,
  });
  if (result.error || result.status !== 0) {
    fail(`FAILED  ${label}` + (result.error ? `: ${result.error.message}` : " — see the output above."));
  }
}

// ── where it installs, and whether a copy is running there ────────────────

function macInstallDir() {
  if (process.env.CROPWATCHER_INSTALL_DIR) return resolve(process.env.CROPWATCHER_INSTALL_DIR);
  try {
    accessSync("/Applications", constants.W_OK);
    return "/Applications";
  } catch {
    return join(homedir(), "Applications");
  }
}

/**
 * Is the copy about to be replaced running? It could be flying a drone, so
 * this refuses rather than killing it — the operator quits it, which lands
 * the drone and ends the session tidily (desktop/src/main.tsx).
 */
function runningCopy(target) {
  if (MAC) {
    const found = spawnSync("pgrep", ["-f", `${target}/Contents/MacOS/`], { encoding: "utf8" });
    return found.status === 0 && found.stdout.trim() !== "";
  }
  if (WINDOWS) {
    for (const image of [`${APP}.exe`, "desktop.exe", "cropwatcher-agent.exe"]) {
      const found = spawnSync("tasklist", ["/FI", `IMAGENAME eq ${image}`, "/NH"],
        { encoding: "utf8", windowsHide: true });
      if ((found.stdout ?? "").toLowerCase().includes(image.toLowerCase())) return true;
    }
  }
  return false;
}

function refuseIfRunning(target) {
  if (INSTALL && runningCopy(target)) {
    fail(`${APP} is running${MAC ? ` from ${target}` : ""}. Quit it first — closing it lands the ` +
      "drone and ends the session — then run this again.");
  }
}

const macTarget = MAC ? join(macInstallDir(), `${APP}.app`) : null;
// Before minutes of building, not after.
refuseIfRunning(macTarget);

// ── 1. setup ──────────────────────────────────────────────────────────────

step("check the toolchain and install what the build needs",
  process.execPath, [join(ROOT, "scripts", "setup.mjs"), ...(flags.includes("--dev") ? ["--dev"] : [])],
  { env: { ...process.env, CROPWATCHER_SETUP_QUIET_NEXT: "1" } });

// ── 2. build ──────────────────────────────────────────────────────────────

const bundles = MAC ? ["--bundles", "app"] : WINDOWS ? ["--bundles", "nsis"] : ["--no-bundle"];
console.log("\n  The first build takes several minutes: Rust compiles everything once.");
step(`build ${APP} ${version} (the flight agent is frozen and verified first)`,
  "pnpm", ["tauri", "build", ...bundles], { cwd: DESKTOP, shell: WINDOWS });

if (!INSTALL) {
  const built = MAC ? join(RELEASE, "bundle", "macos", `${APP}.app`)
    : WINDOWS ? join(RELEASE, "bundle", "nsis") : join(RELEASE, "desktop");
  console.log(`\nBuilt. It is at:\n  ${built}\n`);
  process.exit(0);
}

// ── 3. install ────────────────────────────────────────────────────────────

refuseIfRunning(macTarget);   // it may have been opened during the build
let installed;

if (MAC) {
  const source = join(RELEASE, "bundle", "macos", `${APP}.app`);
  if (!existsSync(source)) fail(`The build finished but ${source} is missing.`);
  console.log(`\n==> install to ${macTarget}`);
  // Replace, never merge: a file the new build no longer ships must not linger.
  rmSync(macTarget, { recursive: true, force: true });
  // ditto keeps what cp -R can lose: symlinks, extended attributes and the
  // code signature inside the bundle.
  step(`copy ${APP}.app`, "ditto", [source, macTarget]);
  for (const part of ["desktop", "cropwatcher-agent"]) {
    if (!existsSync(join(macTarget, "Contents", "MacOS", part))) {
      fail(`Installed, but ${part} is missing from ${macTarget}. Run this again.`);
    }
  }
  installed = macTarget;
} else {
  const folder = join(RELEASE, "bundle", "nsis");
  const setups = existsSync(folder)
    ? readdirSync(folder).filter((f) => f.toLowerCase().endsWith("-setup.exe"))
      .map((f) => join(folder, f)).sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)
    : [];
  if (setups.length === 0) fail(`The build finished but no installer is in ${folder}.`);
  // /S: silent. Tauri's installer defaults to a per-user install, so no
  // administrator prompt; running it again replaces the installed version.
  step(`run ${setups[0].split(/[\\/]/).pop()} silently`, setups[0], ["/S"]);
  const home = join(process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"), APP);
  const exe = existsSync(home)
    ? readdirSync(home).find((f) => f.toLowerCase().endsWith(".exe") && !f.toLowerCase().startsWith("uninstall")
      && !f.toLowerCase().startsWith("cropwatcher-agent"))
    : undefined;
  if (!exe) fail(`The installer ran, but ${APP} is not in ${home}. Run the installer by hand: ${setups[0]}`);
  installed = join(home, exe);
}

console.log(`
Installed ${APP} ${version}:
  ${installed}

Open it from ${MAC ? "Applications or Launchpad" : "the Start menu"}. To update later: git pull, then
run this again.
`);

if (WINDOWS) {
  console.log(`Before the first flight, the Crazyradio needs its Windows driver, once:
  1. Download Zadig from https://zadig.akeo.ie and run it.
  2. Options → List All Devices, then choose "Crazyradio PA USB Dongle".
  3. Pick libusb-win32 as the driver and click Install (or Replace) Driver.
The app says so, too, if it finds the radio without its driver.
`);
}

if (OPEN) {
  if (MAC) spawnSync("open", [installed]);
  else spawnSync("cmd", ["/c", "start", "", installed], { windowsHide: true });
}
