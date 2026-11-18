#!/usr/bin/env python3
"""Resolve trusted recipe runner and release destination before building source."""
import argparse
import json
import os
from common import destination, registry, revision

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("dependency")
parser.add_argument("--ref", default="")
parser.add_argument("--runner", default="")
parser.add_argument("--repository", default="")
args = parser.parse_args()
spec = registry()[args.dependency]
revision(args.ref or spec["default_ref"])
runner = json.loads(args.runner) if args.runner else spec.get("runner", ["ubuntu-24.04"])
if not isinstance(runner, list) or not runner or not all(isinstance(x, str) and x for x in runner):
    raise SystemExit("Runner must be a JSON array of labels")
output = {"runner": json.dumps(runner), "repository": destination(args.dependency, args.repository)}
if os.environ.get("GITHUB_OUTPUT"):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in output.items():
            stream.write(key + "=" + value + "\n")
print(json.dumps(output))
