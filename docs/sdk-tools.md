# Android, SDK and bootstrap tool tasks

The project name is neutral; upstream names appear only where they identify an
actual dependency or its provenance. Each tool below has its own build/release task
and the same optional full commit hash or tag argument.

## Bootstrap tools

- **`depot-tools`** packages a pinned source checkout of depot_tools with `gclient`,
  CIPD and vpython3 launchers. Git, Bash, Python 3, CA certificates, network access
  and archive utilities are prerequisites. Auto-update is disabled. Native Python/
  CIPD runtime components are bootstrapped from upstream on first use; those binaries
  are not source-built by this recipe. The installed libexec directory must be writable.
- **`repo`** packages the pinned Google Repo Python tooling. It is used by the AOSP
  tasks and requires Git/Python. The AOSP bootstrap pins the same Repo revision for
  its internal `.repo/repo` checkout.
- **`gn`** and **`ninja`** build native Linux x64 executables. GN's shallow source
  build reports its source commit rather than inventing a full-history commit count.

## Android SDK tools from AOSP

Tasks: **`aapt2`**, **`aidl`**, **`zipalign`**, **`apksigner`**, **`adb`** and **`fastboot`**.

These use a manifest pinned to the Android 15 initial-release platform graph,
synchronize AOSP using Repo, select the requested component commit, and build the
corresponding host module through Soong. They require the large `aosp-builder`
self-hosted runner and are not scheduled automatically on ordinary hosted runners.

For these tasks the optional ref belongs to the component repository shown in its
recipe. The rest of the platform remains at the pinned manifest. The component
commit and resolved full platform manifest are included in the output. A ref from
a different Android platform release may require updating the manifest as well.

Native outputs and built host shared libraries are packaged together. The apksigner
task also packages its JVM JAR and needs a compatible JDK at runtime. These are
individual tool distributions, not an installer for the whole official Android SDK.
Other SDK components, including SDK platform data, command-line package management,
NDK compilers and D8/R8, are tracked as inputs/future work unless they have an explicit
task in `recipes/registry.json`. A manifest entry alone does not imply a build recipe.

## Dart and Flutter tooling

- **`dart-sdk`** uses the selected SDK Git revision, its gclient DEPS and upstream
  `tools/build.py` to build a Linux x64 Dart SDK from source. It uses `sdk-builder`.
- **`flutter-tools`** selects the upstream SDK Git revision, builds the CLI's Dart
  tool snapshot through upstream bootstrap and precaches Android engine artifacts.
  The release includes `bin/flutter`, `bin/dart`, the SDK checkout, Git metadata and
  the required cached upstream runtimes. This builds the tool snapshot; the matching
  Dart/engine cache binaries are upstream prebuilts, not newly source-built engines.
- **`flutter-engine-arm64`** and **`flutter-engine-armv7`** build the respective
  Android native engine, Java embedding and host AOT snapshot tool from the selected
  monorepo revision. They use its actual CI recipes, replace remote execution with
  local Ninja, and retain resolved source/package revisions. `RUNTIME_MODE` defaults
  to `release`; local builds can select `profile` or `debug` with that environment
  variable. Currently supported refs need the monorepo `engine/src` layout.

These are separate dependency tasks; the root project is not a single engine build
or a pretense that all 299 inventory rows are independently compiled packages.

## Native Android ARM64 host extension

The current host executables are Linux x64/glibc. Android ARM64 requires a distinct
host profile with Bionic-compatible Git/Python/JDK, Dart/SDK host tools, GN/Ninja,
resource/packaging tools and compiler runtime support. Merely changing the Android
engine's output CPU does not port these host tools. Upstream bootstrap binaries and
Gradle-selected aapt2 artifacts also need an ARM-compatible provisioning strategy.

Per-dependency source, target, runner and release-destination fields provide the
extension points. Native Android host execution is documented, not implemented.
