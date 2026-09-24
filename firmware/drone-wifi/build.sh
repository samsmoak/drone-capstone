#!/usr/bin/env bash
# Build the drone firmware: stock Crazyflie release + the drone_wifi app.
#
#   firmware/drone-wifi/build.sh        -> build/cf2.bin
#
# FW_TAG MUST MATCH what the drone runs today (firmware.revision0 read over the
# radio: 0x252b4134 = 2025.12.1, unmodified). Building from any other release
# changes flight behaviour this project has tuned against, not just Wi-Fi.
set -euo pipefail

FW_TAG=2025.12.1
TC_VER=13.3.rel1
CACHE="${CROPWATCHER_CACHE:-$HOME/.cache/cropwatcher}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FW="$CACHE/crazyflie-firmware"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) TC_HOST=darwin-arm64 ;;
  Darwin-x86_64) TC_HOST=darwin-x86_64 ;;
  Linux-x86_64) TC_HOST=x86_64 ;;
  Linux-aarch64) TC_HOST=aarch64 ;;
  *) echo "unsupported build host: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac
TC="$CACHE/toolchain/arm-gnu-toolchain-$TC_VER-$TC_HOST-arm-none-eabi"

if [ ! -x "$TC/bin/arm-none-eabi-gcc" ]; then
  mkdir -p "$CACHE/toolchain"
  curl -fsSL "https://developer.arm.com/-/media/Files/downloads/gnu/$TC_VER/binrel/arm-gnu-toolchain-$TC_VER-$TC_HOST-arm-none-eabi.tar.xz" \
    | tar xJ -C "$CACHE/toolchain"
fi

if [ ! -d "$FW/.git" ]; then
  git clone --filter=blob:none https://github.com/bitcraze/crazyflie-firmware.git "$FW"
fi
git -C "$FW" fetch --tags --quiet
git -C "$FW" checkout --quiet "$FW_TAG"
git -C "$FW" submodule update --init --recursive --quiet

# Kbuild cannot build a path containing a space, and this repo lives under
# "current projects". So the app is built from a copy in the cache.
OOT="$CACHE/oot/drone-wifi"
rm -rf "$OOT" && mkdir -p "$OOT"
cp -R "$HERE/src" "$HERE/Kbuild" "$HERE/Makefile" "$HERE/app-config" "$OOT/"

export PATH="$TC/bin:$PATH"
cd "$OOT"
make CRAZYFLIE_BASE="$FW" cf2_defconfig
# The firmware's merge_config.sh needs GNU readlink and sed. On macOS it fails
# QUIETLY and the build carries on with the app disabled — a firmware that
# flashes fine and never runs drone_wifi. So the app's options are appended
# (the last assignment wins), the broken merge is skipped, and the result is
# checked rather than trusted.
cat app-config >> build/.config
make CRAZYFLIE_BASE="$FW" OOT_CONFIG=/nonexistent -j"$(getconf _NPROCESSORS_ONLN)"
for opt in CONFIG_APP_ENABLE=y CONFIG_DECK_AI=y CONFIG_ENABLE_CPX=y; do
  grep -qx "$opt" build/.config || { echo "build/.config lacks $opt" >&2; exit 1; }
done

mkdir -p "$HERE/build"
cp "$OOT/build/cf2.bin" "$HERE/build/cf2.bin"
ls -l "$HERE/build/cf2.bin"
