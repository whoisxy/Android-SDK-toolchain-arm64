# SDK and bootstrap tools

All compiled release output targets ARM64. `libc` defaults to Bionic; its value is
carried through the compiler profile, archive name, release tag and metadata.
The build machine is allowed to have a different CPU.

## Bootstrap tools

- `repo` is a pinned Python bootstrap source used to synchronize AOSP on the build
  machine. It has no build/release task. `gtest-parallel` is interpreted Python tooling.
- `cipd` builds the native client from pinned LUCI source with Go/CGO and the selected
  ARM64 compiler. `depot-tools` includes it as a dependency, together with gclient and
  caller-managed Python/vpython launchers. Desktop Python/CIPD bootstrap executables
  are not downloaded into the Android release package. Runtime Python packages used
  by depot_tools must be supplied by the target Python environment.
- `gn` and `ninja` build ARM64 native executables. Temporary build-machine utilities
  are kept outside the release prefix.

## Android SDK components

`aapt2`, `aidl`, `zipalign`, `adb` and `fastboot` use a pinned Android platform graph.
Their Bionic builds select the ARM64 product and adapt the selected component's
host-only native module declarations to device modules. The source diff and resolved
platform manifest are retained. Additional upstream source portability problems can
require component-specific patches; the AOSP builds need the large self-hosted
runner and are not claimed verified by a small hosted-library run.

AOSP binaries target the pinned Android platform release and may use platform APIs
newer than the API level used by the NDK library tasks. Architecture/libc checks do
not establish compatibility with older Android system releases.

`apksigner` builds directly from the pinned apksig Java sources on a hosted runner.
The build signs and verifies an APK using the upstream test fixture. The release
contains a JVM archive and launcher for use with a target JDK. The standalone
variant uses the JDK's security providers and excludes cloud KMS integration.

## Dart and Flutter

- `gen-snapshot` builds only Dart's `gen_snapshot` executable for ARM64 and the
  selected libc. Bionic is the default. It uses a standard hosted runner, its own
  pinned upstream compiler dependencies, and releases the executable with source
  provenance and architecture/libc checks. It does not build the entire SDK or
  Flutter engine. The aliases `./task gen_snapshot` and `./task snapshot_gen` select
  the same task.

- `dart-sdk` builds `create_sdk` for ARM64 and the selected operating system, using
  `--os android` for Bionic and `--os linux` for glibc. Resolved gclient dependencies
  are retained. Musl needs a separate upstream SDK port and is rejected explicitly.
- `flutter-tools` includes the source-built ARM64 Dart SDK and builds the tool as a
  portable kernel snapshot. The build-machine Dart executable is not shipped.
  Bionic includes a tool-platform adapter for Android. Device-side app builds also
  need matching engine/helper artifacts and SDK components; the package does not
  claim those complete device workflows were exercised by an ELF check.
- `flutter-engine-arm64` builds the Bionic ARM64 engine, Java embedding and target
  snapshot generator. Desktop gen_snapshot binaries and mixed host zip archives
  are excluded from the release. Bionic is the supported libc for this Android task.

Dart SDK and Flutter tool tasks use a hosted runner with storage cleanup.
The engine task uses the provisioned `sdk-builder`.

## Compiler profiles and verification

The Bionic profile uses the Android NDK and ARM64 ABI; glibc uses the AArch64 GNU
compiler, while musl accepts an AArch64 musl toolchain or a checksum-pinned Zig.
`ANDROID_NDK_HOME`, `ANDROID_API`, `ARM64_GNU_PREFIX`, `ARM64_MUSL_PREFIX` and `ZIG`
provide toolchain configuration. The Actions provisioning step sets these paths.

Both the build and publisher reject wrong-architecture ELF output. They inspect
static-library members, ELF interpreters and incompatible libc dependencies rather
than inferring architecture from a filename. Python/scripts/headers are portable
inputs, not proof that an external Python/JVM runtime is bundled or device-tested.
