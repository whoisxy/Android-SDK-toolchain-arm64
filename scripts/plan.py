#!/usr/bin/env python3
"""Resolve trusted recipe runner and release destination before building source."""
import argparse
import json
import os
from common import destination, registry, source_revision
from targets import LIBCS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("dependency")
parser.add_argument("--ref", default="")
parser.add_argument("--source-url", default="")
parser.add_argument("--runner", default="")
parser.add_argument("--repository", default="")
parser.add_argument("--libc", choices=LIBCS, default="bionic")
args = parser.parse_args()
spec = registry()[args.dependency]
if not spec.get("release_task", True):
    raise SystemExit(args.dependency + " is bootstrap-only; there is no release task")
try:
    source_revision(spec, args.ref, args.source_url)
except ValueError as error:
    raise SystemExit(str(error)) from None
if args.libc not in spec.get("supported_libcs", LIBCS):
    raise SystemExit(f"{args.dependency} does not support libc={args.libc}")
if spec.get("source_required") and args.runner:
    raise SystemExit("Generic CMake builds use the default GitHub-hosted runner")
runner = json.loads(args.runner) if args.runner else spec.get("runner", ["ubuntu-24.04"])
if not isinstance(runner, list) or not runner or not all(isinstance(x, str) and x for x in runner):
    raise SystemExit("Runner must be a JSON array of labels")
def needs_compiler(name):
    entry = registry()[name]
    if entry.get("manages_toolchain") or entry["backend"] in {"dart-sdk", "flutter-tools", "android-engine"}:
        return False
    return entry["kind"] != "jvm-tool" or any(needs_compiler(dep) for dep in entry.get("dependencies", []))

output = {"runner": json.dumps(runner), "repository": destination(args.dependency, args.repository),
          "compiler_required": str(needs_compiler(args.dependency)).lower()}
if os.environ.get("GITHUB_OUTPUT"):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in output.items():
            stream.write(key + "=" + value + "\n")
print(json.dumps(output))
