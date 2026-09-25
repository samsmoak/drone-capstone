"""Freeze the agent into the single binary the desktop app ships.

Run with the agent's own venv Python — `pnpm sidecar` in desktop/ does that
for you (desktop/scripts/sidecar.mjs), on macOS and Windows alike.

This replaced build_sidecar.sh. pnpm runs package scripts through cmd.exe on
Windows, which cannot run a bash script, so every Windows build failed at
`'..' is not recognized` before the installer was ever produced. Python is
already required to build the agent, so the build step is Python too.

Tauri resolves an `externalBin` by appending the Rust target triple to the
configured name, so the file MUST land as `cropwatcher-agent-<triple>` or the
bundler fails with a "binary not found" that names the path it wanted and not
the reason. The triple is read from rustc rather than hardcoded, because an
Intel Mac and an Apple-silicon Mac need different files and the mistake is
invisible until someone else's laptop cannot start the agent.

Cross-compiling is not possible here: PyInstaller freezes for the platform —
and the CPU — of the Python running it. That is why the Python's CPU is
checked against Rust's target below.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE.parent
BIN_DIR = AGENT.parent.parent / "desktop" / "src-tauri" / "bin"
EXE = ".exe" if sys.platform == "win32" else ""

# platform.machine() spellings → the CPU half of a Rust triple.
_CPU = {"arm64": "aarch64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}


class BuildError(RuntimeError):
    """Something a person must fix before the agent can be frozen."""


def _rustc() -> str:
    found = shutil.which("rustc")
    if found:
        return found
    # rustup installs to ~/.cargo/bin, which a login shell's PATH often lacks.
    fallback = Path.home() / ".cargo" / "bin" / f"rustc{EXE}"
    if fallback.exists():
        return str(fallback)
    raise BuildError(
        "Rust is not installed, or rustc is not on PATH. Install it from "
        "https://rustup.rs — or run `node scripts/setup.mjs` from the repo root, "
        "which checks everything the build needs."
    )


def rust_triple() -> str:
    output = subprocess.run([_rustc(), "-vV"], capture_output=True, text=True, check=True).stdout
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise BuildError(f"Could not read the host triple from `rustc -vV`:\n{output}")


def python_cpu() -> str:
    machine = platform.machine().lower()
    return _CPU.get(machine, machine)


def check_cpu(triple: str) -> None:
    """The agent is frozen for THIS Python's CPU; the app for Rust's. They must agree.

    An x86_64 Python under Rosetta on an Apple-silicon Mac would freeze an
    Intel agent and name it for arm64. It would build, bundle and launch —
    under Rosetta — and be the wrong binary in every installer made from it.
    """
    target = triple.split("-", 1)[0]
    if python_cpu() != target:
        raise BuildError(
            f"This Python is {python_cpu()} but Rust builds for {target} ({triple}). The "
            f"agent and the app would be for different processors. Recreate the venv "
            f"with a {target} Python — `node scripts/setup.mjs` does this."
        )


def check_pyinstaller() -> None:
    if importlib.util.find_spec("PyInstaller") is None:
        raise BuildError(
            f"PyInstaller is not installed in {sys.executable}.\n"
            f"Run: {sys.executable} -m pip install -e \"{AGENT}[packaging]\"\n"
            f"(or `node scripts/setup.mjs` from the repo root)."
        )


def build() -> Path:
    triple = rust_triple()
    check_cpu(triple)
    check_pyinstaller()

    print(f"==> freezing agent for {triple}", flush=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", "dist", "--workpath", "build", "cropwatcher-agent.spec"],
        cwd=HERE, check=True,
    )

    # Tauri appends the triple *before* the extension on Windows:
    # cropwatcher-agent-x86_64-pc-windows-msvc.exe
    target = BIN_DIR / f"cropwatcher-agent-{triple}{EXE}"
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "dist" / f"cropwatcher-agent{EXE}", target)
    target.chmod(target.stat().st_mode | 0o111)

    print("==> verifying the frozen binary before it ships", flush=True)
    sys.path.insert(0, str(HERE))
    from verify_sidecar import main as verify

    if verify([str(target)]) != 0:
        raise BuildError("the frozen agent failed verification — see above. Nothing ships.")
    print(f"==> {target}")
    return target


def main() -> int:
    # The spec file and the dist/build folders are relative to this folder.
    os.chdir(HERE)
    try:
        build()
    except BuildError as e:
        print(f"\n  {e}\n", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"\n  {e.cmd[0]} failed with exit code {e.returncode} — see above.\n",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
