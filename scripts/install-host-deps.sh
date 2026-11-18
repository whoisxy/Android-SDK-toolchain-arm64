#!/usr/bin/env bash
set -euo pipefail
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || {
  echo 'Use an Ubuntu 24.04 build runner with an appropriate ARM64 cross toolchain.' >&2; exit 1;
}
privilege=()
if [[ "$EUID" != 0 ]]; then privilege=(sudo -n); fi
"${privilege[@]}" apt-get update
"${privilege[@]}" apt-get install -y --no-install-recommends \
  build-essential clang cmake ninja-build pkg-config python3 python3-dev python3-venv \
  curl git ca-certificates tar unzip zip xz-utils bzip2 autoconf automake libtool \
  meson m4 texinfo nasm yasm bison flex gperf rsync file golang-go \
  libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev \
  libgl1-mesa-dev libglu1-mesa-dev libfontconfig1-dev
