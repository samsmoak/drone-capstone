#!/usr/bin/env bash
#
# Freeze the agent into the single binary the desktop app ships.
#
# Tauri resolves an `externalBin` by appending the Rust target triple to the
# configured name, so the file MUST land as `cropwatcher-agent-<triple>` or the
# bundler fails with a "binary not found" that names the path it wanted and not
# the reason. The triple is read from rustc rather than hardcoded, because an
# Intel Mac and an Apple-silicon Mac need different files and the mistake is
# invisible until someone else's laptop cannot start the agent.
#
# Cross-compiling is not possible here: PyInstaller freezes for the platform it
# runs on. macOS builds the .dmg, Windows builds the .exe, each on its own CI
# runner.
set -euo pipefail

cd "$(dirname "$0")"

VENV="../.venv"
# A Windows venv puts executables in Scripts/, not bin/, and suffixes them.
if [[ -d "$VENV/Scripts" ]]; then
  BIN="$VENV/Scripts"
  EXE=".exe"
else
  BIN="$VENV/bin"
  EXE=""
fi

if [[ ! -x "$BIN/pyinstaller$EXE" ]]; then
  echo "PyInstaller is not installed in $VENV." >&2
  echo "Run: $BIN/pip install pyinstaller" >&2
  exit 1
fi

TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
if [[ -z "$TRIPLE" ]]; then
  echo "Could not read the target triple from rustc. Is Rust on PATH?" >&2
  echo "Rust installs to ~/.cargo/bin, which is not always on a login shell's PATH." >&2
  exit 1
fi

OUT="../../../desktop/src-tauri/bin"

echo "==> freezing agent for $TRIPLE"
"$BIN/pyinstaller$EXE" --clean --noconfirm \
  --distpath ./dist --workpath ./build \
  cropwatcher-agent.spec

# Tauri appends the triple *before* the extension on Windows:
# cropwatcher-agent-x86_64-pc-windows-msvc.exe
TARGET="$OUT/cropwatcher-agent-$TRIPLE$EXE"
mkdir -p "$OUT"
cp "./dist/cropwatcher-agent$EXE" "$TARGET"
chmod +x "$TARGET"

echo "==> verifying the frozen binary before it ships"
"$BIN/python$EXE" ./verify_sidecar.py "$TARGET"

echo "==> $TARGET"
