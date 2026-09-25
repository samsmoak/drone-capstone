// Open the app `pnpm tauri build` just built: the second half of `pnpm app`.
//
// It used to be macOS `open` inline in package.json, which does not exist on
// Windows. What gets opened is the built app itself, not the installer, so the
// result of a change can be seen without installing anything.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const release = resolve(dirname(fileURLToPath(import.meta.url)), "../src-tauri/target/release");

// The Cargo package is "desktop", so that is the executable's name; the
// installers rename it to CropWatcher.
const target = {
  darwin: join(release, "bundle", "macos", "CropWatcher.app"),
  win32: join(release, "desktop.exe"),
}[process.platform] ?? join(release, "desktop");

if (!existsSync(target)) {
  console.error(`\n  Nothing to open at ${target}. Did \`pnpm tauri build\` succeed?\n`);
  process.exit(1);
}

const [command, args] = process.platform === "darwin" ? ["open", [target]] : [target, []];
// Detached: the app outlives this script, which only launches it.
spawn(command, args, { detached: true, stdio: "ignore" }).unref();
console.log(`  opened ${target}`);
