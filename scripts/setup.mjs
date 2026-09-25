#!/usr/bin/env node
// Everything a fresh clone needs before `pnpm app`, on macOS or Windows:
//
//   node scripts/setup.mjs            check, then install
//   node scripts/setup.mjs --check    check only; change nothing
//   node scripts/setup.mjs --dev      also the agent's test and lint tools
//
// One script for every OS, in Node, because Node is the one thing every
// machine building the desktop app already runs (pnpm needs it). A bash
// script and a PowerShell twin would drift; this cannot.
//
// Every check runs before anything is installed, and every problem is listed
// at once with its fix, so a new machine is fixed in one pass rather than one
// error per run. CI runs this same file on every OS it builds for
// (.github/workflows/desktop-release.yml), so it is proven wherever an
// installer is.
//
// It checks, rather than assumes, three things that have each broken a build:
//   - which Python actually runs. Windows' `python` can be a Microsoft Store
//     alias that runs nothing; candidates are executed, not trusted.
//   - that Python's CPU matches Rust's target. PyInstaller freezes for the
//     Python's CPU and Tauri builds for Rust's; an x86_64 Python under Rosetta
//     on an Apple-silicon Mac would ship an Intel agent inside an arm64 app.
//   - that an existing venv still runs here. One copied from another machine
//     (another CPU, a Python that is not installed here) is recreated.

import { spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const AGENT = join(ROOT, "backend", "agent");
const DESKTOP = join(ROOT, "desktop");
const VENV = join(AGENT, ".venv");
const WINDOWS = process.platform === "win32";
const MAC = process.platform === "darwin";
const EXE = WINDOWS ? ".exe" : "";
const VENV_PYTHON = WINDOWS ? join(VENV, "Scripts", "python.exe") : join(VENV, "bin", "python");

const PYTHON_MIN = [3, 11];
const PNPM_MAJOR = 10;
// platform.machine() spellings → the CPU half of a Rust triple.
const CPU = { arm64: "aarch64", aarch64: "aarch64", x86_64: "x86_64", amd64: "x86_64" };

const USAGE = "usage: node scripts/setup.mjs [--check] [--dev]";
const flags = process.argv.slice(2);
for (const flag of flags) {
  if (!["--check", "--dev"].includes(flag)) {
    console.error(`unknown option ${flag}\n${USAGE}`);
    process.exit(2);
  }
}
const CHECK_ONLY = flags.includes("--check");
const DEV = flags.includes("--dev");

// ── output ────────────────────────────────────────────────────────────────

const problems = [];
const ok = (what) => console.log(`  ok   ${what}`);
const note = (what) => console.log(`  --   ${what}`);
const problem = (what, fix) => {
  problems.push({ what, fix });
  console.log(`  NO   ${what}`);
};
const rel = (path) => relative(ROOT, path) || ".";

/** Run a command and capture it. Never throws: a missing program is `ok: false`. */
function run(command, args, { cwd = ROOT, shell = false, timeout = 60_000 } = {}) {
  const result = spawnSync(command, args, { cwd, shell, timeout, encoding: "utf8", windowsHide: true });
  return {
    ok: !result.error && result.status === 0,
    out: (result.stdout ?? "").trim(),
    err: (result.stderr ?? "").trim() || result.error?.message || "",
  };
}

/** Run a command the user should watch (installs). Exits on failure. */
function step(label, command, args, { cwd = ROOT, shell = false } = {}) {
  console.log(`\n==> ${label}`);
  const result = spawnSync(command, args, { cwd, shell, stdio: "inherit", windowsHide: true });
  if (result.error || result.status !== 0) {
    console.error(`\n  FAILED  ${label}` + (result.error ? `: ${result.error.message}` : ""));
    process.exit(1);
  }
}

const versionAtLeast = (have, want) => {
  for (let i = 0; i < want.length; i++) {
    if ((have[i] ?? 0) !== want[i]) return (have[i] ?? 0) > want[i];
  }
  return true;
};

// ── checks ────────────────────────────────────────────────────────────────

function checkNode() {
  const [major, minor] = process.versions.node.split(".").map(Number);
  // Vite's own floor (desktop/node_modules/vite/package.json engines).
  const fine = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major >= 23;
  if (fine) ok(`Node ${process.versions.node}`);
  else problem(`Node ${process.versions.node} is too old for Vite (needs 20.19+ or 22.12+)`,
    "Install Node 24 LTS from https://nodejs.org");
}

/** Rust's host triple, or null when Rust is missing. */
function checkRust() {
  const onPath = run("rustc", ["-vV"]);
  const fallback = join(homedir(), ".cargo", "bin", `rustc${EXE}`);
  const rustc = onPath.ok ? onPath : existsSync(fallback) ? run(fallback, ["-vV"]) : onPath;
  if (!rustc.ok) {
    problem("Rust is not installed",
      "Install it from https://rustup.rs, then open a new terminal and run this again.");
    return null;
  }
  const triple = /^host:\s*(\S+)/m.exec(rustc.out)?.[1];
  const version = /^rustc\s+(\S+)/m.exec(rustc.out)?.[1] ?? "?";
  if (!triple) {
    problem("Could not read Rust's target from `rustc -vV`", "Reinstall Rust from https://rustup.rs");
    return null;
  }
  if (WINDOWS && !triple.endsWith("-msvc")) {
    problem(`Rust targets ${triple}; Tauri on Windows needs the MSVC toolchain`,
      "Run: rustup default stable-msvc");
    return triple;
  }
  if (!onPath.ok) note(`rustc is not on PATH; using ${fallback}. Add ~/.cargo/bin to PATH.`);
  ok(`Rust ${version} (${triple})`);
  return triple;
}

function checkNativeToolchain() {
  if (MAC) {
    if (run("xcode-select", ["-p"]).ok) ok("Xcode Command Line Tools");
    else problem("Xcode Command Line Tools are not installed", "Run: xcode-select --install");
    return;
  }
  if (WINDOWS) {
    const programs = process.env["ProgramFiles(x86)"] ?? "C:\\Program Files (x86)";
    const vswhere = join(programs, "Microsoft Visual Studio", "Installer", "vswhere.exe");
    const found = existsSync(vswhere) && run(vswhere, [
      "-latest", "-products", "*",
      "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
      "-property", "installationPath",
    ]).out;
    if (found) ok("Microsoft C++ Build Tools");
    else problem("Microsoft C++ Build Tools are not installed (Rust needs its linker)",
      "Install them from https://visualstudio.microsoft.com/visual-cpp-build-tools/ " +
      "and tick \"Desktop development with C++\".");

    // Preinstalled on Windows 10 (1803+) and 11; the installer brings it
    // otherwise. Only `pnpm app` on a stripped-down Windows needs it here.
    const webview = run("reg", ["query",
      "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
      "/v", "pv"]);
    if (webview.ok) ok("Microsoft Edge WebView2");
    else note("WebView2 not found in the registry. If the built app opens blank, install it from " +
      "https://developer.microsoft.com/microsoft-edge/webview2/");
    return;
  }
  note(`${process.platform}: not a platform CropWatcher publishes. Tauri's Linux prerequisites ` +
    "are at https://v2.tauri.app/start/prerequisites/");
}

function checkPnpm() {
  // pnpm is a .cmd shim on Windows, which Node only launches through a shell.
  const pnpm = run("pnpm", ["--version"], { shell: WINDOWS });
  const major = Number(pnpm.out.split(".")[0]);
  if (!pnpm.ok) problem("pnpm is not installed", `Run: npm install -g pnpm@${PNPM_MAJOR}`);
  else if (major < PNPM_MAJOR) problem(`pnpm ${pnpm.out} is older than ${PNPM_MAJOR}`,
    `Run: npm install -g pnpm@${PNPM_MAJOR}`);
  else ok(`pnpm ${pnpm.out}`);
}

const PROBE = "import json,platform,sys;" +
  "print(json.dumps([list(sys.version_info[:3]),platform.machine(),sys.executable]))";

/** What a Python actually is, by running it. null when it does not run. */
function probePython(command, prefix = []) {
  const result = run(command, [...prefix, "-c", PROBE], { timeout: 30_000 });
  if (!result.ok) return null;
  try {
    const [version, machine, executable] = JSON.parse(result.out.split(/\r?\n/).pop());
    return { command, prefix, version, cpu: CPU[machine.toLowerCase()] ?? machine.toLowerCase(), executable };
  } catch {
    return null;
  }
}

const pyVersion = (py) => py.version.join(".");

/** A Python ≥ 3.11 for the same CPU Rust builds for. */
function findPython(targetCpu) {
  const candidates = [];
  if (process.env.CROPWATCHER_PYTHON) candidates.push([process.env.CROPWATCHER_PYTHON]);
  // 3.11 first: it is what CI builds with, so it is the proven one.
  if (WINDOWS) {
    candidates.push(["py", "-3.11"], ["py", "-3.12"], ["py", "-3.13"], ["python"], ["py", "-3"]);
  } else {
    candidates.push(["python3.11"], ["python3.12"], ["python3.13"], ["python3"], ["python"]);
  }

  const rejected = [];
  for (const [command, ...prefix] of candidates) {
    const py = probePython(command, prefix);
    if (!py) continue;
    if (!versionAtLeast(py.version, PYTHON_MIN)) {
      rejected.push(`${py.executable} is Python ${pyVersion(py)}`);
      continue;
    }
    if (targetCpu && py.cpu !== targetCpu) {
      rejected.push(`${py.executable} is for ${py.cpu}, but Rust builds for ${targetCpu}`);
      continue;
    }
    ok(`Python ${pyVersion(py)} (${py.cpu}) — ${py.executable}`);
    return py;
  }

  const why = rejected.length ? ` Found, but unusable: ${rejected.join("; ")}.` : "";
  problem(`No Python ${PYTHON_MIN.join(".")}+ ${targetCpu ? `for ${targetCpu} ` : ""}found.${why}`,
    WINDOWS
      ? "Install Python 3.11 from https://www.python.org/downloads/windows/ and tick " +
        "\"Add python.exe to PATH\". (The Microsoft Store `python` alias does not count.)"
      : MAC
        ? "Install Python 3.11 from https://www.python.org/downloads/macos/ (a universal " +
          "installer, right for any Mac), or: brew install python@3.11"
        : "Install Python 3.11 with your package manager.");
  return null;
}

/**
 * Is the existing venv usable HERE? A venv records the absolute path of the
 * Python that made it, so one copied from another machine does not run, and
 * one made by an x86_64 Python on an Apple-silicon Mac freezes the wrong agent.
 */
function venvState(targetCpu) {
  if (!existsSync(VENV)) return { usable: false, why: null };
  const py = probePython(VENV_PYTHON);
  if (!py) return { usable: false, why: "its Python does not run on this machine" };
  if (!versionAtLeast(py.version, PYTHON_MIN)) {
    return { usable: false, why: `it is Python ${pyVersion(py)}; ${PYTHON_MIN.join(".")}+ is needed` };
  }
  if (targetCpu && py.cpu !== targetCpu) {
    return { usable: false, why: `it is for ${py.cpu}, but Rust builds for ${targetCpu}` };
  }
  return { usable: true, why: null, py };
}

// ── main ──────────────────────────────────────────────────────────────────

const os = { darwin: "macOS", win32: "Windows" }[process.platform] ?? process.platform;
console.log(`\nCropWatcher setup — ${os} ${process.arch}${CHECK_ONLY ? " (checking only)" : ""}\n`);

checkNode();
const triple = checkRust();
const targetCpu = triple ? triple.split("-")[0] : null;
checkNativeToolchain();
checkPnpm();
const python = findPython(targetCpu);

const venv = venvState(targetCpu);
if (venv.usable) ok(`agent environment ${rel(VENV)} (Python ${pyVersion(venv.py)})`);
else if (venv.why) note(`agent environment ${rel(VENV)} will be recreated: ${venv.why}`);
else note(`agent environment ${rel(VENV)} will be created`);

if (problems.length) {
  console.log(`\n${problems.length} thing${problems.length === 1 ? "" : "s"} to fix first:\n`);
  for (const { what, fix } of problems) console.log(`  - ${what}\n      ${fix}\n`);
  console.log("Then run this again.\n");
  process.exit(1);
}

if (CHECK_ONLY) {
  console.log("\nEverything needed is here. Run without --check to install.\n");
  process.exit(0);
}

if (!venv.usable) {
  if (existsSync(VENV)) {
    // A venv is disposable by design: everything in it comes from pyproject.
    rmSync(VENV, { recursive: true, force: true });
  }
  step(`create ${rel(VENV)} with Python ${pyVersion(python)}`,
    python.command, [...python.prefix, "-m", "venv", VENV]);
}

step("upgrade pip", VENV_PYTHON,
  ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", "pip"]);
step(`install the flight agent${DEV ? " with its dev tools" : ""}`, VENV_PYTHON,
  ["-m", "pip", "install", "--quiet", "--disable-pip-version-check",
   "-e", `.[${DEV ? "packaging,dev" : "packaging"}]`],
  { cwd: AGENT });
step("install the desktop app's packages", "pnpm", ["install", "--frozen-lockfile"],
  { cwd: DESKTOP, shell: WINDOWS });

console.log(`
Ready. To build the app and open it:

  cd desktop
  pnpm app

The first build takes several minutes (Rust compiles everything once).
To work on the window with live reload instead: pnpm tauri dev
`);

if (WINDOWS) {
  console.log(`On Windows the Crazyradio needs a driver, installed once:
  1. Download Zadig from https://zadig.akeo.ie and run it.
  2. Options → List All Devices, then choose "Crazyradio PA USB Dongle".
  3. Pick libusb-win32 as the driver and click Install (or Replace) Driver.
The app says so, too, if it finds the radio without its driver.
`);
}
