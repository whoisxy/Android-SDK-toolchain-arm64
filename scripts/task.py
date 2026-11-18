#!/usr/bin/env python3
"""A local task builds a dependency, then publishes its output as a GitHub Release."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from common import ROOT, build_environment, destination, registry
from targets import LIBCS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dependency", help="Dependency name, or list")
    parser.add_argument("ref", nargs="?", default="", help="Optional full Git commit hash or tag")
    parser.add_argument("--build-only", action="store_true", help="Skip release publication")
    parser.add_argument("--libc", choices=LIBCS, default="bionic")
    args = parser.parse_args()
    available = registry()
    if args.dependency == "list":
        for name, spec in sorted(available.items()):
            if spec.get("release_task", True):
                print(f"{name:25} {spec['kind']:22} {spec['default_ref']}")
        return
    if args.dependency not in available:
        raise SystemExit("Unknown dependency; run ./task list")
    if not available[args.dependency].get("release_task", True):
        raise SystemExit(args.dependency + " is a bootstrap dependency, not a build/release task")
    selected = ""
    if not args.build_only:
        selected = destination(args.dependency, os.environ.get("RELEASE_REPOSITORY", ""))
        if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
            raise SystemExit("Set GH_TOKEN for local publication, or use --build-only")
    subprocess.run(["bash", str(ROOT / "scripts/build.sh"), args.dependency, args.ref, "--libc", args.libc],
                   env=build_environment(), check=True)
    if not args.build_only:
        subprocess.run([sys.executable, str(ROOT / "scripts/release.py"), str(ROOT / "dist"),
                        "--repository", selected, "--dependency", args.dependency, "--libc", args.libc], check=True)


if __name__ == "__main__":
    main()
