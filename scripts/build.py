#!/usr/bin/env python3
"""Build one registry dependency and package installed output with source provenance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile

from common import ROOT, build_environment, registry, revision
from targets import Arm64Toolchain, LIBCS, target_name, validate_tree


class Builder:
    def __init__(self, dependency, requested_ref, root=None, libc="bionic"):
        self.dependencies = registry()
        if dependency not in self.dependencies:
            raise ValueError(f"Unknown task: {dependency}")
        if not self.dependencies[dependency].get("release_task", True):
            raise ValueError(dependency + " is bootstrap-only, not a compiled release task")
        self.dependency = dependency
        self.libc = libc
        self.target = target_name(libc)
        if libc not in self.dependencies[dependency].get("supported_libcs", LIBCS):
            raise ValueError(f"{dependency} does not support libc={libc}; no fallback target is used")
        self.requested_ref = requested_ref
        self.env = build_environment()
        if self.dependencies[dependency]["backend"] == "android-sdk-tool":
            self.env["ANDROID_API"] = str(max(30, int(self.env.get("ANDROID_API", "28"))))
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
        self._toolchain = None

    @property
    def toolchain(self):
        if self._toolchain is None:
            self._toolchain = Arm64Toolchain(self.libc, self.work / "toolchain", self.env)
        return self._toolchain

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
        if spec["backend"] == "flutter-tools":
            flutter = self.fetch(name, self.requested_ref)
            dart_revision = re.search(
                r"""['"]dart_revision['"]\s*:\s*['"]([0-9a-f]{40})['"]""",
                (flutter / "DEPS").read_text(),
            )
            if dart_revision is None:
                raise ValueError("Cannot determine the matching Dart revision from Flutter DEPS")
            self.fetch("dart-sdk", dart_revision[1])
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
            self.icu(source, build)
        elif backend == "gn":
            # A shallow checkout lacks GN's initial-commit tag. Supply an honest source label.
            (build / "last_commit_position.h").write_text(
                '#define LAST_COMMIT_POSITION_NUM 0\n#define LAST_COMMIT_POSITION "source-' + self.record(name)["commit"][:12] + '"\n')
            self.run(["python3", "build/gen.py", "--no-last-commit-position", "--out-path", build], cwd=source, env=self.toolchain.env)
            self.run(["ninja", "-C", build, "-j", self.jobs], env=self.toolchain.env)
            self.copy(build / "gn", "bin/gn")
        elif backend in ("depot-tools", "repo", "gtest-parallel"):
            self.script_distribution(name, source, backend)
        elif backend == "shaderc":
            self.run(["python3", "utils/git-sync-deps"], cwd=source)
            self.cmake(spec, source, build)
        elif backend in ("skia", "dart-sdk", "gen-snapshot"):
            self.large_build(name, spec, source, build)
        elif backend == "android-sdk-tool":
            self.android_sdk_tool(name, spec, source, build)
        elif backend == "apksigner":
            self.apksigner(source, build)
        elif backend == "flutter-tools":
            self.flutter_tools(source, build)
        elif backend == "android-engine":
            self.android_engine(name, spec, source, build)
        elif backend == "go":
            target_env = dict(self.toolchain.env, GOOS="android" if self.libc == "bionic" else "linux", GOARCH="arm64", CGO_ENABLED="1")
            executable = self.prefix / "bin" / spec["output_name"]
            executable.parent.mkdir(parents=True, exist_ok=True)
            self.run(["go", "build", "-trimpath", "-buildmode=pie", "-ldflags=-s -w", "-o", executable, spec["go_package"]], cwd=source, env=target_env)
        else:
            raise ValueError("Unsupported backend: " + backend)
        self.collect_licenses(source, self.prefix / "share/licenses" / name)
        self.built.add(name)
        self.visiting.remove(name)

    def flutter_tools(self, source, build):
        # The upstream CLI queries its own Git checkout at runtime. Retain the public-source
        # shallow .git metadata; it contains no setup credentials or authenticated remote URL.
        sdk = self.prefix / "sdk/flutter"
        shutil.copytree(source, sdk, ignore=shutil.ignore_patterns('__pycache__'))
        host_sdk = source
        if self.libc == "bionic":
            for checkout in (sdk, host_sdk):
                platform_file = checkout / "packages/flutter_tools/lib/src/base/platform.dart"
                original = platform_file.read_text()
                needle = "String get operatingSystem => io.Platform.operatingSystem;"
                if needle not in original:
                    raise ValueError("Selected tool revision needs an updated Android platform adapter")
                platform_file.write_text(original.replace(needle, "String get operatingSystem => io.Platform.isAndroid ? 'linux' : io.Platform.operatingSystem;"))
        env = dict(self.env, CI="true", FLUTTER_SUPPRESS_ANALYTICS="true",
                   DART_SUPPRESS_ANALYTICS="true", PUB_ENVIRONMENT="sdk-toolchain-build",
                   PUB_CACHE=str(build / "host-pub-cache"))
        # Build-machine Dart is used only to compile a portable kernel snapshot, never shipped.
        self.run([host_sdk / "bin/flutter", "--version", "--machine"], cwd=host_sdk, env=env)
        cache = sdk / "bin/cache"
        cache.mkdir(parents=True, exist_ok=True)
        self.run([host_sdk / "bin/cache/dart-sdk/bin/dart", "--snapshot-kind=kernel",
                  "--snapshot=" + str(cache / "flutter_tools.snapshot"),
                  "--packages=" + str(host_sdk / "packages/flutter_tools/.dart_tool/package_config.json"),
                  host_sdk / "packages/flutter_tools/bin/flutter_tools.dart"], cwd=host_sdk, env=env)
        # Flutter's command code discovers Dart in its own cache, independently of PATH.
        for stamp in ("engine.stamp", "engine.realm"):
            path = host_sdk / "bin/cache" / stamp
            if path.exists():
                shutil.copy2(path, cache / stamp)
        (cache / "dart-sdk").symlink_to("../../../dart", target_is_directory=True)
        self.run([host_sdk / "bin/cache/dart-sdk/bin/dart", "--disable-dart-dev",
                  cache / "flutter_tools.snapshot", "--help"], cwd=host_sdk,
                 env=dict(env, FLUTTER_ROOT=str(sdk)))
        # The portable snapshot above used build-machine Dart. Only target Dart is packaged.
        (self.prefix / "bin").mkdir(exist_ok=True)
        dart_wrapper = self.prefix / "bin/dart"
        dart_wrapper.write_text(('#!/system/bin/sh\n' if self.libc == 'bionic' else '#!/bin/sh\n') + 'set -eu\n'
            'prefix="$(cd -- "$(dirname -- "$0")/.." && pwd)"\n'
            'exec "$prefix/sdk/dart/bin/dart" "$@"\n')
        dart_wrapper.chmod(0o755)
        wrapper = self.prefix / "bin/flutter"
        wrapper.write_text(('#!/system/bin/sh\n' if self.libc == 'bionic' else '#!/bin/sh\n') + 'set -eu\n'
            'prefix="$(cd -- "$(dirname -- "$0")/.." && pwd)"\n'
            'export FLUTTER_ROOT="$prefix/sdk/flutter"\n'
            'exec "$prefix/bin/dart" --disable-dart-dev "$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot" "$@"\n')
        wrapper.chmod(0o755)
        (self.prefix / "TOOL_SNAPSHOT.md").write_text(
            "The CLI is a portable kernel snapshot paired with the source-built ARM64 Dart SDK for the selected libc. Build-machine Dart and desktop engine caches are not bundled. The Bionic build adapts the tool platform abstraction to Android. Device-side app builds also require matching ARM64 engine/helper artifacts and Android SDK tools; this package does not claim those device workflows were exercised.\n")

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
        if mode in {"release", "profile"} and "gen_snapshot" not in targets:
            targets.append("gen_snapshot")
        self.run(["python3", src / "flutter/tools/gn", *flags], cwd=src, env=env)
        output = src / "out" / name
        self.run([ninja, "-C", output, "-j", self.jobs, *targets], cwd=src, env=env)
        for artifact in ("libflutter.so", "flutter.jar"):
            self.copy(output / artifact, artifact)
        if mode in {"release", "profile"}:
            self.copy(output / "gen_snapshot", "bin/gen_snapshot")
        metadata = self.prefix / "share/build-metadata"
        metadata.mkdir(parents=True, exist_ok=True)
        self.run([depot / "gclient", "revinfo", "--actual", "--output-json",
                  metadata / "resolved-engine-dependencies.json"], cwd=source, env=env)

    def android_sdk_tool(self, name, spec, source, build):
        lock = json.loads((ROOT / "recipes/android-sdk-sources.json").read_text())
        adapter = build / "sdk-tools"
        adapter.mkdir()

        def checkout(remote, commit, path):
            path.mkdir(parents=True, exist_ok=True)
            self.run(["git", "init", "--quiet", path])
            self.run(["git", "-C", path, "fetch", "--quiet", "--depth=1", remote, commit])
            self.run(["git", "-C", path, "checkout", "--quiet", "--detach", "FETCH_HEAD"])

        checkout(lock["adapter"]["url"], lock["adapter"]["revision"], adapter)
        self.collect_licenses(adapter, self.prefix / "share/licenses/android-sdk-tools-port")

        def prepare(pin):
            path = adapter / pin["path"]
            if pin["path"] == spec["sdk_source_path"]:
                path.parent.mkdir(exist_ok=True)
                path.symlink_to(source, target_is_directory=True)
                return dict(pin, revision=self.record(name)["commit"])
            checkout(pin["url"], pin["revision"], path)
            return pin

        with ThreadPoolExecutor(max_workers=min(self.jobs, 6)) as pool:
            resolved = list(pool.map(prepare, lock["sources"]))

        # Apply the pinned port's source preparation without executing its clone
        # commands, which would resolve mutable tag or branch names.
        self.run(["python3", "-c", "import get_source; get_source.patches()"], cwd=adapter)
        self.run(["patch", "--batch", "--forward", "-p1", "-i",
                  adapter / "patches/protobuf_CMakeLists.txt.patch"], cwd=adapter)

        protoc = shutil.which("protoc")
        if protoc is None or self.run([protoc, "--version"], capture=True) != "libprotoc 3.21.12":
            raise ValueError("The Android SDK port requires host protoc 3.21.12")
        output = build / "out"
        self.run(["cmake", "-S", adapter, "-B", output, "-G", "Ninja",
                  "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                  "-Dprotobuf_BUILD_TESTS=OFF", "-DABSL_PROPAGATE_CXX_STD=ON",
                  "-DPROTOC_PATH=" + protoc, *self.toolchain.cmake])
        self.run(["cmake", "--build", output, "--parallel", self.jobs, "--target", name])
        executable = output / "bin" / spec["sdk_output_group"] / name
        self.run([self.toolchain.strip, "--strip-debug", executable])
        self.copy(executable, "bin/" + name)
        metadata = self.prefix / "share/build-metadata"
        metadata.mkdir(parents=True, exist_ok=True)
        (metadata / "android-sdk-sources.json").write_text(
            json.dumps({**lock, "sources": resolved}, indent=2) + "\n"
        )

    def apksigner(self, source, build):
        core = source / "src/main/java"
        cli = source / "src/apksigner/java"
        classes = build / "classes"
        shutil.copytree(cli, classes, ignore=shutil.ignore_patterns("*.java"))
        main = cli / "com/android/apksigner/ApkSignerTool.java"
        # Standalone OpenJDK provides the cryptography. The AOSP-only provider uses
        # desktop JNI, which would introduce an incompatible native dependency.
        original = main.read_text()
        standalone = re.sub(r"(?ms)^([ \t]*)// BEGIN-AOSP\n.*?^\1// END-AOSP\n", "", original)
        if "org.conscrypt." in standalone:
            raise ValueError("Standalone apksigner needs an updated provider adapter for this revision")
        main.write_text(standalone)
        java_sources = sorted(
            path for path in core.rglob("*.java")
            if not any(part in {"aws", "gcp"} for part in path.relative_to(core).parts)
        ) + sorted(cli.rglob("*.java"))
        sources_file = build / "java-sources"
        sources_file.write_text("".join(json.dumps(str(path)) + "\n" for path in java_sources))
        self.run(["javac", "--release", "8", "-encoding", "UTF-8", "-d", classes, "@" + str(sources_file)])
        jar = self.prefix / "framework/apksigner.jar"
        jar.parent.mkdir()
        self.run(["jar", "--create", "--file", jar, "--manifest",
                  source / "src/apksigner/apksigner.mf", "-C", classes, "."])
        wrapper = self.prefix / "bin/apksigner"
        wrapper.parent.mkdir(exist_ok=True)
        wrapper.write_text(("#!/system/bin/sh\n" if self.libc == "bionic" else "#!/bin/sh\n") +
                           'set -eu\nprefix="$(cd -- "$(dirname -- "$0")/.." && pwd)"\n'
                           'exec java -jar "$prefix/framework/apksigner.jar" "$@"\n')
        wrapper.chmod(0o755)
        # Exercise both operations with upstream's non-production test APK and key.
        fixtures = source / "src/test/resources/com/android/apksig"
        signed = build / "signed.apk"
        command = ["java", "-jar", jar]
        self.run([*command, "sign", "--key", fixtures / "rsa-2048.pk8",
                  "--cert", fixtures / "rsa-2048.x509.pem",
                  "--out", signed, fixtures / "empty-unsigned.apk"])
        self.run([*command, "verify", "--verbose", signed])

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
                   "-DCMAKE_PREFIX_PATH=" + str(self.prefix),
                   "-DCMAKE_FIND_ROOT_PATH=" + str(self.prefix),
                   *self.toolchain.cmake, *spec.get("cmake_options", [])]
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
        self.run([self.toolchain.cc, "-O2", "-fPIC", "-DSQLITE_THREADSAFE=1", "-c", amalgamation, "-o", build / "sqlite3.o"])
        self.run([self.toolchain.ar, "rcs", build / "libsqlite3.a", build / "sqlite3.o"])
        self.run([self.toolchain.cc, "-shared", "-Wl,-soname,libsqlite3.so", build / "sqlite3.o", "-ldl", "-lpthread", "-lm", "-o", build / "libsqlite3.so"])
        for name in ("libsqlite3.a", "libsqlite3.so"):
            self.copy(build / name, "lib/" + name)
        for name in ("sqlite3.h", "sqlite3ext.h"):
            if (source / name).exists():
                self.copy(source / name, "include/" + name)

    def libtess2(self, source, build):
        objects = []
        for c_file in sorted((source / "Source").glob("*.c")):
            obj = build / (c_file.stem + ".o")
            self.run([self.toolchain.cc, "-O2", "-fPIC", "-I", source / "Include", "-c", c_file, "-o", obj])
            objects.append(obj)
        if not objects:
            raise ValueError("No libtess2 C sources found")
        self.run([self.toolchain.ar, "rcs", build / "libtess2.a", *objects])
        self.copy(build / "libtess2.a", "lib/libtess2.a")
        self.copy(source / "Include", "include/libtess2")

    def script_distribution(self, name, source, backend):
        destination = "libexec/" + name
        shutil.copytree(source, self.prefix / destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.git', '__pycache__', 'tests', 'testing', '.cipd_bin'))
        bins = self.prefix / "bin"
        bins.mkdir(exist_ok=True)
        launchers = {"repo": ["repo"], "depot-tools": ["gclient", "cipd", "vpython3"],
                     "gtest-parallel": ["gtest-parallel"]}[backend]
        for tool in launchers:
            if not (source / tool).exists():
                raise ValueError("Missing launcher: " + tool)
            launcher = bins / tool
            command = ('exec python3 "$prefix/libexec/' + name + '/' + tool + '" "$@"\n')
            if backend == "depot-tools":
                entry = "gclient.py" if tool == "gclient" else tool
                command = ('exec python3 "$prefix/libexec/' + name + '/' + entry + '" "$@"\n') if tool == "gclient" else 'exec python3 "$@"\n' if tool == "vpython3" else 'exec "${CIPD_ANDROID_BINARY:-$prefix/bin/cipd-native}" "$@"\n'
            launcher.write_text(('#!/system/bin/sh\n' if self.libc == 'bionic' else '#!/bin/sh\n') + 'set -eu\n'
                'prefix="$(cd -- "$(dirname -- "$0")/.." && pwd)"\n'
                'export DEPOT_TOOLS_UPDATE=0\n'
                + ('export PATH="$prefix/libexec/depot-tools:$PATH"\n' if backend == 'depot-tools' else '')
                + command)
            launcher.chmod(0o755)
        if backend == "depot-tools":
            # Bootstrapped Python/CIPD binaries are intentionally not claimed as source-built.
            (self.prefix / "DEPOT_TOOLS_RUNTIME.md").write_text(
                "This is the pinned architecture-independent depot_tools script distribution. The Android launchers use an installed Python 3 and require a native ARM64 CIPD client via CIPD_ANDROID_BINARY for CIPD operations. They do not download desktop-Linux Python/CIPD executables. vpython3 uses the caller-managed Python environment. These runtime dependencies are not bundled by the script-distribution task.\n")

    def icu(self, source, build):
        host = build / "host"
        host.mkdir()
        self.run([source / "source/runConfigureICU", "Linux", "--disable-tests", "--disable-samples"], cwd=host)
        self.run(["make", "-j", self.jobs], cwd=host)
        target = build / "arm64"
        target.mkdir()
        self.run([source / "source/configure", "--host=aarch64-linux-android" if self.libc == "bionic" else "--host=aarch64-linux-gnu" if self.libc == "glibc" else "--host=aarch64-linux-musl",
                  "--with-cross-build=" + str(host), "--prefix=" + str(self.prefix),
                  "--disable-tests", "--disable-samples"], cwd=target, env=self.toolchain.env)
        self.run(["make", "-j", self.jobs], cwd=target, env=self.toolchain.env)
        self.run(["make", "install"], cwd=target, env=self.toolchain.env)

    def large_build(self, name, spec, source, build):
        depot = self.fetch("depot-tools")
        env = dict(self.env, PATH=str(depot) + os.pathsep + self.env["PATH"])
        if name == "skia":
            self.run(["python3", "tools/git-sync-deps"], cwd=source, env=env)
            import json as _json
            args = spec["gn_args"] + ' target_cpu="arm64"'
            if self.libc == "bionic":
                args += ' target_os="android" ndk=' + _json.dumps(self.toolchain.details["ndk"]) + ' ndk_api=' + str(self.toolchain.android_api)
            else:
                args += ' target_os="linux" cc=' + _json.dumps(self.toolchain.cc) + ' cxx=' + _json.dumps(self.toolchain.cxx) + ' ar=' + _json.dumps(self.toolchain.ar)
            self.run([source / "bin/gn", "gen", build, "--args=" + args], cwd=source, env=env)
            self.run(["ninja", "-C", build, "-j", self.jobs, "skia"], env=env)
            self.copy(build / "libskia.a", "lib/libskia.a")
            self.copy(source / "include", "include/skia/include")
        else:
            checkout = build / "checkout"
            checkout.mkdir()
            sdk = checkout / "sdk"
            self.run(["git", "clone", "--no-hardlinks", source, sdk])
            config = [{"name": "sdk", "url": spec["url"], "managed": False, "deps_file": "DEPS", "custom_deps": {},
                       "custom_vars": {"download_android_deps": self.libc == "bionic"}}]
            (checkout / ".gclient").write_text("solutions = " + repr(config) + "\n")
            self.run([depot / "gclient", "sync", "--no-history", "--revision", "sdk@" + self.record(name)["commit"]], cwd=checkout, env=env)
            target = "gen_snapshot" if spec["backend"] == "gen-snapshot" else "create_sdk"
            configuration = ["--no-rbe", "--mode", "release", "--arch", "arm64",
                             "--os", "android" if self.libc == "bionic" else "linux"]
            self.run(["python3", "tools/gn.py", *configuration], cwd=sdk, env=env)
            directories = list(sdk.glob("out/Release*ARM64"))
            if len(directories) != 1:
                raise ValueError("Could not locate generated ARM64 Dart build configuration")
            self.run([sdk / "buildtools/ninja/ninja", "-C", directories[0], "-j", self.jobs, target], cwd=sdk, env=env)
            if spec["backend"] == "gen-snapshot":
                candidates = list(sdk.glob("out/Release*ARM64/gen_snapshot"))
                if len(candidates) != 1:
                    raise ValueError("Could not locate the target ARM64 gen_snapshot executable")
                self.copy(candidates[0], "bin/gen_snapshot")
            else:
                candidates = list(sdk.glob("out/Release*ARM64/dart-sdk"))
                if len(candidates) != 1:
                    raise ValueError("Could not locate the built ARM64 Dart SDK")
                self.copy(candidates[0], "sdk/dart" if self.dependency == "flutter-tools" else ".")
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
        if platform.system() != "Linux":
            raise ValueError("The configured builders run on Linux; release output is always ARM64")
        spec = self.dependencies[self.dependency]
        if shutil.disk_usage(self.work).free < spec.get("min_disk_gib", 3) * 1024**3:
            raise ValueError("Insufficient disk space for this recipe")
        self.install(self.dependency)
        architecture_report = validate_tree(self.prefix, self.libc)
        if spec["kind"] not in {"headers", "script-distribution", "jvm-tool"} and not (architecture_report["elf_files"] or architecture_report["static_members"]):
            raise ValueError("Native recipe produced no verifiable ARM64 binary output")
        for pc in self.prefix.rglob("*.pc"):
            if pc.is_file() and not pc.is_symlink():
                pc.write_text(pc.read_text().replace("prefix=" + str(self.prefix), "prefix=${pcfiledir}/../.."))
        metadata_dir = self.prefix / "share/build-metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        selected = self.record(self.dependency)
        receipt = {"schema_version": 1, "dependency": self.dependency, "kind": spec["kind"],
                   "requested_ref": self.requested_ref or spec["default_ref"],
                   "source_commit": selected["commit"], "source_url": spec["url"],
                   "host": "linux-" + platform.machine(), "sources": self.records,
                   "target": self.target, "architecture": "arm64", "libc": self.libc,
                   "architecture_validation": architecture_report,
                   "target_toolchain": ({**self._toolchain.details, "cc": self._toolchain.cc, "cxx": self._toolchain.cxx}
                                        if self._toolchain else {"source": "upstream build graph or architecture-independent distribution"}),
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
        archive_name = f"{self.dependency}-{self.target}-{selected['commit'][:12]}.tar.gz"
        output = ROOT / "dist"
        output.mkdir(exist_ok=True)
        archive = output / archive_name
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.prefix, arcname=f"{self.dependency}-{self.target}")
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
    parser.add_argument("--libc", choices=LIBCS, default="bionic")
    args = parser.parse_args()
    Builder(args.dependency, args.ref, libc=args.libc).package()


if __name__ == "__main__":
    main()
