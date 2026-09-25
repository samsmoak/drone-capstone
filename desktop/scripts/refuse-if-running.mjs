// Refuse to build while CropWatcher is running from the build folder.
//
// `pnpm tauri build` rewrites src-tauri/target/release/bundle/macos/
// CropWatcher.app in place — and that is exactly the copy `pnpm app` opens. A
// running program whose signed code is overwritten underneath it can be killed
// by macOS without warning; on 2026-09-25 a copy running there stopped 24 s
// after a rebuild replaced it. That copy may be flying a drone. On Windows the
// same build fails instead, because the running .exe is locked.
//
// So a build stops here and says so. Quitting the app lands the drone and ends
// the session (desktop/src/main.tsx); killing it would not.

import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const release = resolve(dirname(fileURLToPath(import.meta.url)), "../src-tauri/target/release");

function runningFromBuildFolder() {
  if (process.platform === "darwin") {
    const bundle = join(release, "bundle", "macos", "CropWatcher.app", "Contents", "MacOS");
    const found = spawnSync("pgrep", ["-f", `${bundle}/`], { encoding: "utf8" });
    return found.status === 0 && found.stdout.trim() !== "";
  }
  if (process.platform === "win32") {
    // tasklist has no paths; PowerShell does. Only the build folder's copy
    // matters — an installed CropWatcher is elsewhere and is not touched.
    const exe = join(release, "desktop.exe").toLowerCase();
    const found = spawnSync("powershell", ["-NoProfile", "-Command",
      "Get-Process desktop -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
      { encoding: "utf8", windowsHide: true });
    return (found.stdout ?? "").toLowerCase().split(/\r?\n/).some((p) => p.trim() === exe);
  }
  return false;
}

if (runningFromBuildFolder()) {
  console.error(
    "\n  CropWatcher is running from the build folder, and this build would replace it" +
    "\n  while it runs. Quit it first — closing it lands the drone and ends the session —" +
    "\n  then build again.\n",
  );
  process.exit(1);
}
