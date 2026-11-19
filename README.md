# Android SDK toolchain dependency tasks

One build workflow for Android SDK and Flutter dependencies. **Release output is ARM64.**
The build machine's CPU is independent of the output CPU; the default Actions
runner is Ubuntu 24.04 x64 and uses cross compilers.

The `libc` parameter defaults to **`bionic`**. Select `glibc` or `musl` when needed:

| libc | Output target | Toolchain |
|---|---|---|
| `bionic` (default) | Android ARM64 | Pinned Android NDK; API 28 for NDK-built tools |
| `glibc` | Linux ARM64 | AArch64 GNU cross compiler |
| `musl` | Linux ARM64 | AArch64 musl compiler or checksum-pinned Zig |

Each dependency is available in the same Actions dropdown and through `./task`.
Leave the Git hash or tag empty to build the pinned commit.

## Run a task

In Actions, open **Build and release dependency**, click **Run workflow**, and
choose a dependency from the dropdown. The `ref` and `libc` fields are optional.
Using GitHub CLI on your own machine:

```bash
gh workflow run build.yml --repo whoisxy/Android-SDK-toolchain-arm64 \
  -f dependency=zlib -f ref=v1.3.1 -f libc=bionic
```

Locally, provision a compiler for the selected libc, then run:

```bash
export ANDROID_NDK_HOME=/path/to/android-ndk
./task zlib v1.3.1 --libc bionic --build-only
./task zlib v1.3.1 --libc glibc --build-only
./task zlib v1.3.1 --libc musl --build-only
```

Omit `--build-only` to create a release too; local publishing needs
`GITHUB_REPOSITORY=whoisxy/Android-SDK-toolchain-arm64` and a `GH_TOKEN` supplied
through your own environment or secret manager.

`./task list` lists available tasks. [docs/tasks.md](docs/tasks.md) lists source pins,
runners and supported libc combinations. Unsupported combinations fail explicitly;
there is no fallback to the build machine's CPU or a different libc.

## Build and release behavior

Recipes are defined in `recipes/registry.json`. The default ref is an immutable
commit. An override changes the selected dependency; its declared dependency
recipes or AOSP platform graph stay pinned, so a different upstream version may
require recipe changes.

The shared pipeline builds without release write credentials, then passes output
to a separate publisher job. Before publishing, it checks archive integrity,
ARM64 ELF headers, object files inside static libraries, embedded native JAR files,
libc interpreters and incompatible dynamic libc dependencies. Releases contain
compiled output, including JVM bytecode for `apksigner`. These checks complement
execution on a device with the selected runtime.

A successful task creates a release **in this repository**, attaching an output
archive and SHA-256 sidecar. Names and tags contain the output target and libc,
not the runner CPU. Failed uploads retain a draft instead of publishing an
incomplete release. See [docs/releases.md](docs/releases.md).

## Tools and runners

Tasks include native libraries, Android SDK tools, `depot-tools`, CIPD,
GN/Ninja, Dart SDK, the Flutter tool snapshot and the ARM64 Android engine.
See [docs/sdk-tools.md](docs/sdk-tools.md) for tool-specific details and limits.

Most small tasks use the standard hosted runner. Large tasks need provisioned
self-hosted machines:

- `sdk-builder`: labels `self-hosted, linux, x64, sdk-builder` for larger builds
  such as standalone Skia. Dart SDK and Flutter builds use GitHub-hosted runners.
- Android SDK tools build on hosted runners using pinned component sources,
  CMake and the Android NDK.

Those labels select an existing build machine, not the output architecture. The
workflow's optional `runner` JSON input can select another compatible runner.
An ARM64 build machine needs compiler executables that run on that machine;
the target remains ARM64 regardless. Upstream bootstrap tools may impose additional
build-host requirements; an architecture-independent build dispatcher does not
make every upstream build system portable to every operating system.

`JOBS` controls compilation parallelism. `BUILD_ROOT` selects intermediate storage;
`dist/` contains completed archives. Administrators should reclaim completed build
directories on self-hosted runners according to their retention policy.

## Extending the registry

Add a recipe, then run `python3 scripts/generate-tasks.py` to update the workflow
dropdown and dependency list. Set a recipe's `release_repository` to publish
to a separate initialized repository later. Such a destination uses the optional
`RELEASE_TOKEN` secret; same-repository releases use the automatic `GITHUB_TOKEN`.

`inventory/source-dependencies.json` retains the broader source/package inventory.
Rows without an implemented recipe are inventory entries, not standalone builds.
Recipe presence is not proof that every task/libc combination has passed a build.
