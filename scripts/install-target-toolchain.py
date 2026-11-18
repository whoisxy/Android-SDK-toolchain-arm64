#!/usr/bin/env python3
"""Provision the compiler for ARM64 output; it runs on the selected build machine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request

from common import ROOT
from targets import LIBCS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("libc", nargs="?", choices=LIBCS, default="bionic")
args = parser.parse_args()
lock = json.loads((ROOT / "recipes/toolchains.json").read_text())
updates = {}
if args.libc == "bionic":
    ndk = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
    if not ndk:
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if not sdk:
            raise SystemExit("Set ANDROID_NDK_HOME or ANDROID_HOME for Android ARM64 builds")
        path = Path(sdk) / "ndk" / lock["android_ndk"]
        if not path.exists():
            manager = shutil.which("sdkmanager") or str(Path(sdk) / "cmdline-tools/latest/bin/sdkmanager")
            subprocess.run([manager, "--install", "ndk;" + lock["android_ndk"]], check=True)
        ndk = str(path)
    updates.update(ANDROID_NDK_HOME=ndk, ANDROID_API=str(lock["android_api"]))
elif args.libc == "glibc":
    if not shutil.which(os.environ.get("ARM64_GNU_PREFIX", "aarch64-linux-gnu-") + "gcc"):
        privilege = [] if os.geteuid() == 0 else ["sudo", "-n"]
        subprocess.run([*privilege, "apt-get", "update"], check=True)
        subprocess.run([*privilege, "apt-get", "install", "-y", "gcc-aarch64-linux-gnu", "g++-aarch64-linux-gnu", "binutils-aarch64-linux-gnu"], check=True)
else:
    if not (os.environ.get("ARM64_MUSL_PREFIX") or os.environ.get("ZIG") or shutil.which("zig")):
        machine = "aarch64" if platform.machine() in {"aarch64", "arm64"} else "x86_64"
        spec = lock["zig"][machine + "-linux"]
        base = Path(os.environ.get("RUNNER_TEMP", ROOT / "work")) / "target-toolchains"
        base.mkdir(parents=True, exist_ok=True)
        archive = base / "zig.tar.xz"
        with urllib.request.urlopen(spec["tarball"], timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != spec["shasum"]:
            raise SystemExit("Zig compiler archive checksum mismatch")
        with tarfile.open(archive, "r:xz") as source:
            source.extractall(base, filter="data")
        updates["ZIG"] = str(next(base.glob("zig-*/zig")))
if os.environ.get("GITHUB_ENV"):
    with open(os.environ["GITHUB_ENV"], "a") as output:
        for key, value in updates.items():
            output.write(key + "=" + value + "\n")
for key, value in updates.items():
    print(key + "=" + value)
