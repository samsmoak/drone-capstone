#!/usr/bin/env bash
# Build the AI deck's GAP8 camera firmware: Bitcraze's image streamer + our patch.
#
#   firmware/aideck-gap8/build.sh           -> build/aideck_gap8.bin   (JPEG)
#   firmware/aideck-gap8/build.sh --stock   -> build/aideck_gap8_stock.bin
#
# WHY. The stock streamer sends every frame RAW: 324 x 244 = 79 056 bytes,
# over a Wi-Fi link that delivered 0.7–4.9 frames a second in the lab
# (docs/features/desktop/camera.txt). Bitcraze's own code can JPEG-encode each
# frame instead — at most 15 KB, the buffer it allocates — but the choice is a
# compile-time constant (streamerMode in wifi-img-streamer.c), so using it means
# building. jpeg-streamer.patch flips that constant and nothing else.
#
# --stock builds the same source unpatched. Bitcraze publish that one as
# aideck_gap8_wifi_img_streamer_with_ap.bin; building it here and comparing is
# how this script is checked against their release.
#
# IN DOCKER, AND ONLY THIS. The GAP SDK supports Linux only, and Bitcraze build
# their release in their own image (release.yml: `docker run ... bitcraze/aideck
# ./tools/build/build`). The agent and the app never touch a container
# (CLAUDE.md, invariant 7) — this produces one firmware file, flashed over the
# radio by the agent's own flasher (camera/flash_gap8.py). The image is amd64;
# on Apple silicon it runs emulated, which is slow but only once.
set -euo pipefail

GAP8_TAG=2025.02
HERE="$(cd "$(dirname "$0")" && pwd)"
CACHE="${CROPWATCHER_CACHE:-$HOME/.cache/cropwatcher}"
SRC="$CACHE/aideck-gap8-build"
IMAGE="bitcraze/aideck"

STOCK=0
if [ "${1:-}" = "--stock" ]; then STOCK=1; fi

if [ ! -d "$SRC/.git" ]; then
  git clone --filter=blob:none https://github.com/bitcraze/aideck-gap8-examples.git "$SRC"
fi
git -C "$SRC" fetch --tags --quiet
git -C "$SRC" checkout --quiet --force "$GAP8_TAG"
git -C "$SRC" submodule update --init --recursive --quiet
git -C "$SRC" clean -fdxq
if [ "$STOCK" = 0 ]; then
  git -C "$SRC" apply "$HERE/jpeg-streamer.patch"
fi

docker run --rm --platform linux/amd64 -v "$SRC":/module "$IMAGE" \
  bash -c "./tools/build/build"

OUT="$SRC/examples/other/wifi-img-streamer/BUILD/GAP8_V2/GCC_RISCV_FREERTOS/target.board.devices.flash.img"
NAME=$([ "$STOCK" = 1 ] && echo aideck_gap8_stock.bin || echo aideck_gap8.bin)
mkdir -p "$HERE/build"
cp "$OUT" "$HERE/build/$NAME"
ls -l "$HERE/build/$NAME"
shasum -a 256 "$HERE/build/$NAME"
