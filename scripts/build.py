#!/usr/bin/env python3
"""Build one registry dependency and package installed output with source provenance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile

from common import ROOT, build_environment, registry, revision


class Builder:
    def __init__(self, dependency, requested_ref, root=None):
        self.dependencies = registry()
        if dependency not in self.dependencies:
            raise ValueError(f"Unknown task: {dependency}")
        self.dependency = dependency
        self.requested_ref = requested_ref
        self.env = build_environment()
        self.jobs = int(self.env.get("JOBS", "4"))
        if not 1 <= self.jobs <= 256:
            raise ValueError("JOBS must be between 1 and 256")
        base = Path(root or self.env.get("BUILD_ROOT", ROOT / "work"))
        base.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix=dependency + "-", dir=base)).resolve()
        self.prefix = self.work / "prefix"
        self.prefix.mkdir()
        self.sources, self.records, self.built, self.visiting = {}, [], set(), set()
        self.commands = []

    def run(self, arguments, cwd=None, env=None, capture=False):
        arguments = [str(x) for x in arguments]
        print("+ " + " ".join(arguments), flush=True)
        self.commands.append({"argv": arguments, "cwd": str(cwd or self.work)})
        result = subprocess.run(arguments, cwd=cwd or self.work, env=env or self.env,
                                check=True, text=True, capture_output=capture)
        return result.stdout.strip() if capture else None

    def fetch(self, name, selected=None):
        if name in self.sources:
            return self.sources[name]
        spec = self.dependencies[name]
        ref, kind = revision(selected or spec["default_ref"])
        source = self.work / "sources" / name
        source.mkdir(parents=True)
        self.run(["git", "init", "--initial-branch=build", source])
        self.run(["git", "-C", source, "remote", "add", "origin", spec["url"]])
        wanted = ref if kind == "commit" else "refs/tags/" + ref
        self.run(["git", "-C", source, "fetch", "--depth=1", "origin", wanted])
        self.run(["git", "-C", source, "checkout", "--detach", "FETCH_HEAD"])
        sha = self.run(["git", "-C", source, "rev-parse", "HEAD"], capture=True)
        self.records.append({"dependency": name, "url": spec["url"], "requested_ref": ref,
                             "ref_type": kind, "commit": sha})
        self.sources[name] = source
        return source

    def install(self, name):
        if name in self.built:
            return
        if name in self.visiting:
            raise ValueError("Recipe dependency cycle: " + name)
        self.visiting.add(name)
        spec = self.dependencies[name]
        for dependency in spec.get("dependencies", []):
            self.install(dependency)
        source = self.fetch(name, self.requested_ref if name == self.dependency else None)
        for placement in spec.get("source_dependencies", []):
            dep_source = self.fetch(placement["dependency"])
            location = source / placement["path"]
            location.parent.mkdir(parents=True, exist_ok=True)
            if location.exists() and location.is_dir() and not any(location.iterdir()):
                location.rmdir()
            if location.exists() or location.is_symlink():
                raise ValueError("Recipe source dependency would overwrite " + str(location))
            location.symlink_to(dep_source, target_is_directory=True)
        backend = spec["backend"]
        build = self.work / "build" / name
        build.mkdir(parents=True)
        if backend == "cmake":
            self.cmake(spec, source, build)
        elif backend == "sqlite":
            self.sqlite(source, build)
        elif backend == "libtess2":
            self.libtess2(source, build)
        elif backend == "icu":
            self.run([source / "source/runConfigureICU", "Linux", "--prefix=" + str(self.prefix),
                      "--disable-tests", "--disable-samples"], cwd=build)
            self.run(["make", "-j", self.jobs], cwd=build)
            self.run(["make", "install"], cwd=build)
        elif backend == "gn":
            # A shallow checkout lacks GN's initial-commit tag. Supply an honest source label.
            (build / "last_commit_position.h").write_text(
                '#define LAST_COMMIT_POSITION_NUM 0\n#define LAST_COMMIT_POSITION "source-' + self.record(name)["commit"][:12] + '"\n')
            self.run(["python3", "build/gen.py", "--no-last-commit-position", "--out-path", build], cwd=source)
            self.run(["ninja", "-C", build, "-j", self.jobs])
            self.copy(build / "gn", "bin/gn")
        elif backend in ("depot-tools", "repo", "gtest-parallel"):
            self.script_distribution(name, source, backend)
        elif backend == "shaderc":
            self.run(["python3", "utils/git-sync-deps"], cwd=source)
            self.cmake(spec, source, build)
        elif backend in ("skia", "dart-sdk"):
            self.large_build(name, spec, source, build)
        elif backend == "aosp":
            self.aosp(spec, source, build)
        elif backend == "flutter-tools":
            self.flutter_tools(source)
        elif backend == "android-engine":
            self.android_engine(name, spec, source, build)
        else:
            raise ValueError("Unsupported backend: " + backend)
        self.collect_licenses(source, self.prefix / "share/licenses" / name)
        self.built.add(name)
        self.visiting.remove(name)

    def flutter_tools(self, source):
        # The upstream CLI queries its own Git checkout at runtime. Retain the public-source
        # shallow .git metadata; it contains no setup credentials or authenticated remote URL.
        sdk = self.prefix / "sdk/flutter"
        shutil.copytree(source, sdk, ignore=shutil.ignore_patterns('__pycache__'))
        env = dict(self.env, CI="true", FLUTTER_SUPPRESS_ANALYTICS="true",
                   DART_SUPPRESS_ANALYTICS="true", PUB_ENVIRONMENT="sdk-toolchain-build",
                   PUB_CACHE=str(sdk / "bin/cache/pub-cache"))
        self.run([sdk / "bin/flutter", "--version", "--machine"], cwd=sdk, env=env)
        self.run([sdk / "bin/flutter", "precache", "--android"], cwd=sdk, env=env)
        for tool in ("flutter", "dart"):
            wrapper = self.prefix / "bin" / tool
            wrapper.parent.mkdir(parents=True, exist_ok=True)
            wrapper.write_text('#!/usr/bin/env bash\nset -euo pipefail\n'
                'prefix="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                'export PUB_CACHE="${PUB_CACHE:-$prefix/sdk/flutter/bin/cache/pub-cache}"\n'
                'exec "$prefix/sdk/flutter/bin/' + tool + '" "$@"\n')
            wrapper.chmod(0o755)
        (self.prefix / "TOOL_SNAPSHOT.md").write_text(
            "The CLI source comes from the selected Git revision and its Dart tool snapshot is built during SDK bootstrap. The SDK downloads matching upstream Dart/engine binaries and Android caches; those binaries are not source-built by this task. Use dart-sdk or the Android engine tasks for separate source builds.\n")

    def android_engine(self, name, spec, source, build):
        depot = self.fetch("depot-tools")
        ninja = source / "third_party/ninja/ninja"
        env = dict(self.env, PATH=str(depot) + os.pathsep + self.env["PATH"])
        config = [{"name": ".", "url": spec["url"], "managed": False, "deps_file": "DEPS",
                   "custom_deps": {}, "custom_vars": {
                       "download_android_deps": True, "download_linux_deps": True,
                       "download_fuchsia_deps": False, "download_windows_deps": False,
                       "download_emsdk": False, "setup_githooks": False, "use_rbe": False}}]
        (source / ".gclient").write_text("solutions = " + repr(config) + "\n")
        self.run([depot / "gclient", "sync", "--no-history", "--jobs", self.jobs,
                  "--revision", ".@" + self.record(name)["commit"]], cwd=source, env=env)
        src = source / "engine/src"
        mode = self.env.get("RUNTIME_MODE", "release")
        if mode not in {"debug", "profile", "release"}:
            raise ValueError("RUNTIME_MODE must be debug, profile or release")
        variant = "android_" + mode + ("_arm64" if spec["android_cpu"] == "arm64" else "")
        filename = "linux_android_debug_engine.json" if mode == "debug" else "linux_android_aot_engine.json"
        recipes = json.loads((src / "flutter/ci/builders" / filename).read_text())
        selected = next(x for x in recipes["builds"] if x["name"] == "ci/" + variant)
        flags = list(selected["gn"])
        flags[flags.index("--target-dir") + 1] = name
        flags = ["--no-rbe" if x == "--rbe" else x for x in flags]
        targets = list(selected["ninja"]["targets"])
        for target in ("flutter/shell/platform/android:embedding_jars", "flutter/shell/platform/android:abi_jars"):
            if target not in targets:
                targets.append(target)
        self.run(["python3", src / "flutter/tools/gn", *flags], cwd=src, env=env)
        output = src / "out" / name
        self.run([ninja, "-C", output, "-j", self.jobs, *targets], cwd=src, env=env)
        for artifact in ("libflutter.so", "flutter.jar"):
            self.copy(output / artifact, artifact)
        if mode in {"release", "profile"}:
            self.copy(output / "clang_x64/gen_snapshot", "clang_x64/gen_snapshot")
        if (output / "zip_archives").exists():
            self.copy(output / "zip_archives", "zip_archives")
        metadata = self.prefix / "share/build-metadata"
        metadata.mkdir(parents=True, exist_ok=True)
        self.run([depot / "gclient", "revinfo", "--actual", "--output-json",
                  metadata / "resolved-engine-dependencies.json"], cwd=source, env=env)

    def aosp(self, spec, source, build):
        checkout = build / "aosp"
        checkout.mkdir()
        repo = self.prefix / "bin/repo"
        repo_ref = self.dependencies["repo"]["default_ref"]
        self.run([repo, "init", "-u", spec["manifest_url"], "-b", spec["manifest_ref"],
                  "--depth=1", "--no-clone-bundle", "--repo-rev=" + repo_ref], cwd=checkout)
        self.run([repo, "sync", "--current-branch", "--no-tags", "--no-clone-bundle", "-j", self.jobs], cwd=checkout)
        component = checkout / spec["aosp_project_path"]
        # The optional ref selects this component; the remaining platform graph stays manifest-pinned.
        self.run(["git", "fetch", source, "HEAD"], cwd=component)
        self.run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=component)
        manifest_dir = self.prefix / "share/build-metadata"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        self.run([repo, "manifest", "-r", "-o", manifest_dir / "aosp-manifest.xml"], cwd=checkout)
        out = build / "out"
        env = dict(self.env, OUT_DIR=str(out), TARGET_PRODUCT="aosp_x86_64",
                   TARGET_RELEASE="trunk_staging", TARGET_BUILD_VARIANT="userdebug",
                   BUILD_NUMBER=self.env.get("GITHUB_RUN_ID", "local"))
        self.run([checkout / "build/soong/soong_ui.bash", "--make-mode", "-j" + str(self.jobs),
                  *spec["aosp_modules"]], cwd=checkout, env=env)
        host = out / "host/linux-x86"
        for relative in spec["aosp_outputs"]:
            self.copy(host / relative, relative)
        for libdir in ("lib64", "lib"):
            if (host / libdir).exists():
                self.copy(host / libdir, libdir)
        self.collect_licenses(component, self.prefix / "share/licenses/aosp-component")

    def record(self, name):
        return next(x for x in self.records if x["dependency"] == name)

    def copy(self, source, relative):
        target = self.prefix / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".git", "__pycache__"))
        else:
            shutil.copy2(source, target)

    def cmake(self, spec, source, build):
        source_dir = source / spec.get("source_subdir", "")
        options = ["-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_LIBDIR=lib",
                   "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                   "-DCMAKE_CXX_STANDARD=17", "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
                   "-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib",
                   "-DCMAKE_INSTALL_PREFIX=" + str(self.prefix),
                   "-DCMAKE_PREFIX_PATH=" + str(self.prefix), *spec.get("cmake_options", [])]
        self.run(["cmake", "-S", source_dir, "-B", build, "-G", "Ninja", *options])
        targets = spec.get("build_targets", [])
        self.run(["cmake", "--build", build, "--parallel", self.jobs,
                  *(["--target", *targets] if targets else [])])
        if spec.get("install") == "boringssl":
            self.copy(source / "include/openssl", "include/openssl")
            for lib in ("crypto", "ssl"):
                candidates = [build / ("lib" + lib + ".a"), build / lib / ("lib" + lib + ".a")]
                found = next((x for x in candidates if x.exists()), None)
                if found is None:
                    raise ValueError("Missing BoringSSL output " + lib)
                self.copy(found, "lib/" + found.name)
            executable = next((x for x in (build / "tool/bssl", build / "bssl", build / "bin/bssl") if x.exists()), None)
            if executable is None:
                raise ValueError("Missing BoringSSL bssl executable")
            self.copy(executable, "bin/bssl")
        else:
            self.run(["cmake", "--install", build])

    def sqlite(self, source, build):
        amalgamation = source / "sqlite3.c"
        if not amalgamation.exists():
            raise ValueError("This sqlite recipe requires an amalgamation checkout containing sqlite3.c")
        self.run(["cc", "-O2", "-fPIC", "-DSQLITE_THREADSAFE=1", "-c", amalgamation, "-o", build / "sqlite3.o"])
        self.run(["ar", "rcs", build / "libsqlite3.a", build / "sqlite3.o"])
        self.run(["cc", "-shared", "-Wl,-soname,libsqlite3.so", build / "sqlite3.o", "-ldl", "-lpthread", "-lm", "-o", build / "libsqlite3.so"])
        for name in ("libsqlite3.a", "libsqlite3.so"):
            self.copy(build / name, "lib/" + name)
        for name in ("sqlite3.h", "sqlite3ext.h"):
            if (source / name).exists():
                self.copy(source / name, "include/" + name)

    def libtess2(self, source, build):
        objects = []
        for c_file in sorted((source / "Source").glob("*.c")):
            obj = build / (c_file.stem + ".o")
            self.run(["cc", "-O2", "-fPIC", "-I", source / "Include", "-c", c_file, "-o", obj])
            objects.append(obj)
        if not objects:
            raise ValueError("No libtess2 C sources found")
        self.run(["ar", "rcs", build / "libtess2.a", *objects])
        self.copy(build / "libtess2.a", "lib/libtess2.a")
        self.copy(source / "Include", "include/libtess2")

    def script_distribution(self, name, source, backend):
        destination = "libexec/" + name
        self.copy(source, destination)
        bins = self.prefix / "bin"
        bins.mkdir(exist_ok=True)
        launchers = {"repo": ["repo"], "depot-tools": ["gclient", "cipd", "vpython3"],
                     "gtest-parallel": ["gtest-parallel"]}[backend]
        for tool in launchers:
            if not (source / tool).exists():
                raise ValueError("Missing launcher: " + tool)
            launcher = bins / tool
            command = 'exec "$prefix/libexec/' + name + '/' + tool + '" "$@"\n'
            launcher.write_text('#!/usr/bin/env bash\nset -euo pipefail\n'
                'prefix="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                'export DEPOT_TOOLS_UPDATE=0\n'
                + ('export PATH="$prefix/libexec/depot-tools:$PATH"\n' if backend == 'depot-tools' else '')
                + command)
            launcher.chmod(0o755)
        if backend == "depot-tools":
            # Bootstrapped Python/CIPD binaries are intentionally not claimed as source-built.
            (self.prefix / "DEPOT_TOOLS_RUNTIME.md").write_text(
                "This is the pinned depot_tools script distribution. First invocation downloads upstream native Python/CIPD runtime components and needs network access and a writable libexec/depot-tools directory. It does not rebuild those binaries.\n")

    def large_build(self, name, spec, source, build):
        depot = self.fetch("depot-tools")
        env = dict(self.env, PATH=str(depot) + os.pathsep + self.env["PATH"])
        if name == "skia":
            self.run(["python3", "tools/git-sync-deps"], cwd=source, env=env)
            self.run([source / "bin/gn", "gen", build, "--args=" + spec["gn_args"]], cwd=source, env=env)
            self.run(["ninja", "-C", build, "-j", self.jobs, "skia"], env=env)
            self.copy(build / "libskia.a", "lib/libskia.a")
            self.copy(source / "include", "include/skia/include")
        else:
            checkout = build / "checkout"
            checkout.mkdir()
            sdk = checkout / "sdk"
            self.run(["git", "clone", "--no-hardlinks", source, sdk])
            config = [{"name": "sdk", "url": spec["url"], "managed": False, "deps_file": "DEPS", "custom_deps": {}}]
            (checkout / ".gclient").write_text("solutions = " + repr(config) + "\n")
            self.run([depot / "gclient", "sync", "--no-history", "--revision", "sdk@" + self.record(name)["commit"], cwd=checkout, env=env)
            self.run(["python3", "tools/build.py", "--mode", "release", "--arch", "x64", "create_sdk"], cwd=sdk, env=env)
            self.copy(sdk / "out/ReleaseX64/dart-sdk", ".")
            metadata = self.prefix / "share/build-metadata"
            metadata.mkdir(parents=True, exist_ok=True)
            self.run([depot / "gclient", "revinfo", "--actual", "--output-json",
                      metadata / "resolved-sdk-dependencies.json"], cwd=checkout, env=env)

    @staticmethod
    def collect_licenses(source, destination):
        # Preserve available top-level notices; upstream binary/data licenses may need further review.
        for path in source.iterdir():
            if path.is_file() and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")):
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination / path.name)

    def package(self):
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise ValueError("Current recipes run on Linux x64. Android ARM host support is not implemented.")
        spec = self.dependencies[self.dependency]
        if shutil.disk_usage(self.work).free < spec.get("min_disk_gib", 3) * 1024**3:
            raise ValueError("Insufficient disk space for this recipe")
        self.install(self.dependency)
        for pc in self.prefix.rglob("*.pc"):
            if pc.is_file() and not pc.is_symlink():
                pc.write_text(pc.read_text().replace("prefix=" + str(self.prefix), "prefix=${pcfiledir}/../.."))
        metadata_dir = self.prefix / "share/build-metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        selected = self.record(self.dependency)
        receipt = {"schema_version": 1, "dependency": self.dependency, "kind": spec["kind"],
                   "requested_ref": self.requested_ref or spec["default_ref"],
                   "source_commit": selected["commit"], "source_url": spec["url"],
                   "host": "linux-x86_64", "sources": self.records,
                   "target": spec.get("target", "linux-x86_64"),
                   "recipe": spec, "commands": self.commands,
                   "pipeline_commit": self.env.get("GITHUB_SHA", "local"),
                   "workflow_run_id": self.env.get("GITHUB_RUN_ID", "local"),
                   "notes": "Source-built outputs or assembled script/header distributions as indicated by kind. System build packages and some upstream runtime/dependency downloads remain external inputs."}
        if shutil.which("dpkg-query"):
            packages = subprocess.run(["dpkg-query", "-W"], text=True, capture_output=True, check=True)
            (metadata_dir / "host-packages.txt").write_text(packages.stdout)
        # Nested sync tools may fetch extra source trees pinned by the selected upstream revision.
        nested = []
        for directory, folders, files in os.walk(self.work / "sources"):
            if ".git" in folders:
                checkout = Path(directory)
                sha = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], env=self.env, text=True).strip()
                nested.append({"path": str(checkout.relative_to(self.work)), "commit": sha})
            folders[:] = [x for x in folders if x not in {".git", "out", "node_modules"}]
        receipt["observed_source_checkouts"] = nested
        (metadata_dir / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
        archive_name = f"{self.dependency}-linux-x86_64-{selected['commit'][:12]}.tar.gz"
        output = ROOT / "dist"
        output.mkdir(exist_ok=True)
        archive = output / archive_name
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.prefix, arcname=f"{self.dependency}-linux-x86_64")
        digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
        (output / (archive_name + ".sha256")).write_text(digest + "  " + archive_name + "\n")
        (output / "build.json").write_text(json.dumps({**receipt, "assets": [archive_name, archive_name + ".sha256"],
                                                      "archive_sha256": digest}, indent=2) + "\n")
        print("Packaged " + str(archive), flush=True)
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dependency")
    parser.add_argument("ref", nargs="?", default="")
    args = parser.parse_args()
    Builder(args.dependency, args.ref).package()


if __name__ == "__main__":
    main()
