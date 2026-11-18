#!/usr/bin/env bash
set -euo pipefail
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || {
  echo 'Use an Ubuntu 24.04 build runner with an appropriate ARM64 cross toolchain.' >&2; exit 1;
}
privilege=()
if [[ "$EUID" != 0 ]]; then privilege=(sudo -n); fi
packages=()
require_tool() {
  command -v "$1" >/dev/null || packages+=("$2")
}
apt_options=(-o Acquire::Retries=1 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20)
case "${1:-all}" in
  apksigner)
    require_tool javac openjdk-21-jdk-headless
    ;;
  dart-sdk|gen-snapshot|flutter-tools|flutter-engine-arm64|zlib|aapt|aapt2|aidl|zipalign|adb|fastboot)
    for tool in curl git unzip zip tar python3 file cmake; do
      require_tool "$tool" "$tool"
    done
    require_tool xz xz-utils
    require_tool ninja ninja-build
    require_tool g++ build-essential
    case "$1" in
      aapt|aapt2|aidl|zipalign|adb|fastboot)
        require_tool patch patch
        require_tool bison bison
        require_tool flex flex
        require_tool go golang-go
        python3 -c 'import requests' 2>/dev/null || packages+=(python3-requests)
        ;;
    esac
    ;;
  *)
    packages=(build-essential clang cmake ninja-build pkg-config python3 python3-dev python3-venv
      curl git ca-certificates tar unzip zip xz-utils bzip2 autoconf automake libtool
      meson m4 texinfo nasm yasm bison flex gperf rsync file golang-go
      patch protobuf-compiler python3-requests openjdk-21-jdk-headless
      libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev
      libgl1-mesa-dev libglu1-mesa-dev libfontconfig1-dev)
    ;;
esac
if ((${#packages[@]})); then
  "${privilege[@]}" apt-get "${apt_options[@]}" update
  "${privilege[@]}" apt-get "${apt_options[@]}" install -y --no-install-recommends "${packages[@]}"
fi
