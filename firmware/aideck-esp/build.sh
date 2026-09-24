#!/usr/bin/env bash
# Build the AI deck's ESP32 firmware: Bitcraze's release + our patch.
#
#   firmware/aideck-esp/build.sh        -> build/aideck_esp.bin
#
# WHY A PATCH. The stock ESP32 firmware can close one Wi-Fi client twice (the
# send task and the receive task both close it), leaving a stale "disconnected"
# bit that makes EVERY later client disconnect the instant it is accepted — the
# camera then never streams again until a power-cycle. close-client-once.patch
# closes each client once and clears stale bits before accepting. See
# docs/features/desktop/camera.txt.
#
# Built with ESP-IDF v4.3.1 — the version Bitcraze builds with — installed
# natively in the cache (no Docker: Docker Desktop is not part of this project
# and was not working on the build Mac). First run installs it (~600 MB).
set -euo pipefail

ESP_TAG=2025.02
HERE="$(cd "$(dirname "$0")" && pwd)"
CACHE="${CROPWATCHER_CACHE:-$HOME/.cache/cropwatcher}"
SRC="$CACHE/aideck-esp-firmware"

if [ ! -d "$SRC/.git" ]; then
  git clone --filter=blob:none https://github.com/bitcraze/aideck-esp-firmware.git "$SRC"
fi
git -C "$SRC" fetch --tags --quiet
git -C "$SRC" checkout --quiet --force "$ESP_TAG"
git -C "$SRC" clean -fdxq
git -C "$SRC" apply "$HERE/close-client-once.patch"

IDF="$CACHE/esp-idf"
export IDF_TOOLS_PATH="$CACHE/espressif"
if [ ! -d "$IDF/.git" ]; then
  git clone -b v4.3.1 --depth 1 --recursive --shallow-submodules \
    https://github.com/espressif/esp-idf.git "$IDF"
  # gdbgui (a debugging GUI, not needed to build) pins a 2019 gevent that
  # does not build on current macOS; its two helpers go with it.
  sed -i.bak '/^gdbgui==/d;/^pygdbmi/d;/^python-socketio/d' "$IDF/requirements.txt"
  PATH="/usr/bin:$PATH" "$IDF/install.sh" esp32
  # ESP-IDF 4.3 imports pkg_resources, which setuptools removed in 2025.
  "$(ls -d "$IDF_TOOLS_PATH"/python_env/idf4.3_py*_env/bin/python | head -1)" \
    -m pip install -q "setuptools<70"
fi
# ESP-IDF 4.3's scripts call `python`; macOS has only python3. A one-link
# shim in the cache, pointing at the toolchain's own virtualenv (the system
# /usr/bin/python3 is an xcode-select stub that fails under another name).
SHIM="$CACHE/pyshim"
VENV_PY="$(ls -d "$IDF_TOOLS_PATH"/python_env/idf4.3_py*_env/bin/python | head -1)"
mkdir -p "$SHIM" && ln -sf "$VENV_PY" "$SHIM/python"
export PATH="$SHIM:/usr/bin:$PATH"
# export.sh reads unset variables; strict mode is relaxed for it alone.
export IDF_PATH="$IDF"
set +eu
# shellcheck disable=SC1091
. "$IDF/export.sh" >/dev/null
set -eu
# CMake 4 refuses ESP-IDF 4.3's bundled mbedtls (cmake_minimum_required < 3.5);
# this is CMake's own documented escape hatch for exactly that.
export CMAKE_POLICY_VERSION_MINIMUM=3.5
(cd "$SRC" && idf.py build)

mkdir -p "$HERE/build"
cp "$SRC/build/aideck_esp.bin" "$HERE/build/aideck_esp.bin"
ls -l "$HERE/build/aideck_esp.bin"
