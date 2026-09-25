// Freeze and verify the flight agent: `pnpm sidecar`, and the first half of
// `pnpm tauri build` (beforeBuildCommand → build:all).
//
// This file only finds the agent's venv Python and hands over to
// backend/agent/packaging/build_sidecar.py. It exists because pnpm runs
// package scripts through cmd.exe on Windows: a script that named a bash file
// failed there with "'..' is not recognized", and the venv's Python lives at
// .venv/bin/python on macOS but .venv/Scripts/python.exe on Windows. Node is
// the one thing every machine building this already runs.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const agent = resolve(dirname(fileURLToPath(import.meta.url)), "../../backend/agent");
const python = process.platform === "win32"
  ? join(agent, ".venv", "Scripts", "python.exe")
  : join(agent, ".venv", "bin", "python");

if (!existsSync(python)) {
  console.error(
    `\n  The agent has no Python environment yet (looked for ${python}).\n` +
    "  From the repository root, run:  node scripts/setup.mjs\n",
  );
  process.exit(1);
}

const result = spawnSync(python, [join(agent, "packaging", "build_sidecar.py")], {
  stdio: "inherit",
});
if (result.error) {
  console.error(`\n  Could not run ${python}: ${result.error.message}\n` +
    "  Recreate the environment with:  node scripts/setup.mjs\n");
  process.exit(1);
}
process.exit(result.status ?? 1);
