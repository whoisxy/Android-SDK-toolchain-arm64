#!/usr/bin/env python3
"""Publish completed build archives as GitHub Release assets; never execute artifact content."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

from common import ROOT, destination, registry
from targets import LIBCS, target_name, validate_archive


def completed_build(directory):
    directory = Path(directory).resolve()
    metadata = directory / "build.json"
    if metadata.is_symlink() or metadata.stat().st_size > 2 * 1024**2:
        raise ValueError("Invalid build metadata")
    build = json.loads(metadata.read_text())
    if build["dependency"] not in registry():
        raise ValueError("Unknown dependency in build artifact")
    if not re.fullmatch(r"[0-9a-f]{40}", build["source_commit"]):
        raise ValueError("Missing resolved source commit")
    if build.get("architecture") != "arm64" or build.get("libc") not in LIBCS:
        raise ValueError("Release output must declare ARM64 and a supported libc")
    if build.get("target") != target_name(build["libc"]):
        raise ValueError("Artifact target does not match the selected libc")
    assets = build["assets"]
    if not isinstance(assets, list) or len(assets) != 2 or len(set(assets)) != 2:
        raise ValueError("Expected one archive and one checksum file")
    paths = []
    for name in assets:
        if not isinstance(name, str) or name != Path(name).name or name in {"", ".", ".."}:
            raise ValueError("Asset names must be plain filenames")
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
            raise ValueError("Asset is not a regular file within the artifact directory")
        paths.append(path)
    archive = next((x for x in paths if x.name.endswith(".tar.gz")), None)
    if archive is None:
        raise ValueError("Missing build archive")
    checksum = directory / (archive.name + ".sha256")
    if checksum not in paths:
        raise ValueError("Missing matching checksum file")
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != build["archive_sha256"] or checksum.read_text().strip() != actual + "  " + archive.name:
        raise ValueError("Build archive checksum mismatch")
    observed = validate_archive(archive, build["libc"])
    if registry()[build["dependency"]]["kind"] not in {"headers", "script-distribution", "jvm-tool"} and not (observed["elf_files"] or observed["static_members"]):
        raise ValueError("Native release contains no verified ARM64 binary")
    return build, paths


class GitHub:
    def __init__(self):
        self.token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("Release publishing requires GH_TOKEN; Actions supplies GITHUB_TOKEN automatically")

    def api(self, path, method="GET", payload=None):
        request = urllib.request.Request("https://api.github.com" + path,
            data=None if payload is None else json.dumps(payload).encode(), method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "sdk-toolchain-release-task"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read()).get("message", "HTTP error")
            except ValueError:
                message = "HTTP error"
            raise RuntimeError(f"GitHub {method} {path}: HTTP {error.code}: {message}") from None


def publish(directory, repository="", expected_dependency="", expected_libc="bionic"):
    build, assets = completed_build(directory)
    if expected_dependency and build["dependency"] != expected_dependency:
        raise ValueError("Artifact dependency does not match the requested task")
    if build["libc"] != expected_libc:
        raise ValueError("Artifact libc does not match the requested task")
    repository = destination(build["dependency"], repository)
    github = GitHub()
    repo_info = github.api("/repos/" + repository)
    current = os.environ.get("GITHUB_REPOSITORY", "")
    target = os.environ.get("GITHUB_SHA") if repository == current else None
    target = target or repo_info["default_branch"]
    run_id = os.environ.get("GITHUB_RUN_ID", str(time.time_ns()))
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not re.fullmatch(r"[0-9]+", run_id + attempt):
        raise ValueError("Invalid workflow run identifier")
    tag = f"{build['dependency']}/{build['target']}/{build['source_commit'][:12]}-{run_id}-{attempt}"
    body = "\n".join([
        f"Dependency: `{build['dependency']}`", f"Requested source: `{build['requested_ref']}`",
        f"Resolved commit: `{build['source_commit']}`", f"Source: {build['source_url']}",
        f"Build platform: `{build['host']}`", f"Output kind: `{build['kind']}`",
        f"Output target: `{build.get('target', build['host'])}`",
        "", "Archive contains installed output, available license files and build provenance.",
        "The SHA-256 sidecar verifies the archive contents. This release does not imply a device/runtime test.",
    ])
    release = github.api("/repos/" + repository + "/releases", "POST", {
        "tag_name": tag, "target_commitish": target,
        "name": f"{build['dependency']} · {build['requested_ref']} · {build['target']}",
        "body": body, "draft": True, "prerelease": False,
    })
    print("Created draft release " + release["html_url"], flush=True)
    upload_env = dict(os.environ, GH_TOKEN=github.token)
    # gh streams large assets; credentials remain in the environment, not argv or files.
    subprocess.run(["gh", "release", "upload", tag, *map(str, assets),
                    "--repo", repository], env=upload_env, check=True)
    uploaded = github.api("/repos/" + repository + "/releases/" + str(release["id"]))
    observed = {x["name"]: x["size"] for x in uploaded["assets"]}
    if any(observed.get(path.name) != path.stat().st_size for path in assets):
        raise RuntimeError("Release asset verification failed; draft retained for inspection")
    published = github.api("/repos/" + repository + "/releases/" + str(release["id"]),
                           "PATCH", {"draft": False, "make_latest": "false"})
    print("Published " + published["html_url"], flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as stream:
            stream.write(f"### {build['dependency']} release\n\n[{tag}]({published['html_url']})\n")
    return published


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "dist")
    parser.add_argument("--repository", default="")
    parser.add_argument("--dependency", default="")
    parser.add_argument("--libc", choices=LIBCS, default="bionic")
    args = parser.parse_args()
    publish(args.directory, args.repository, args.dependency, args.libc)
