# Android SDK toolchain dependency tasks

> Setup is awaiting workflow-file write permission. See [SETUP_STATUS.md](SETUP_STATUS.md). Build task sources are available; Actions workflow files are not published yet.

One repository of independent source build and release tasks. The initial build
host is **Ubuntu 24.04 / Linux x64**. Running the host tools on **Android ARM64** is
a later extension; Android engine outputs already have separate ARM64/ARMv7 tasks.

Each implemented dependency has:

- A `tasks/NAME.sh [GIT_HASH_OR_TAG]` command.
- A **Build and release NAME** GitHub Actions workflow.
- An immutable default source commit in `recipes/registry.json`.
- A release archive, SHA-256 sidecar and embedded build/source provenance.

See [the complete task list](docs/tasks.md), [Android and SDK tools](docs/sdk-tools.md),
and [release credentials and destinations](docs/releases.md).

## Run a dependency task in Actions

Open **Actions**, select a dependency, then **Run workflow**. Leave `ref` empty to
use its pinned commit, or enter a full Git commit hash or tag from the recipe's
source repository. Branch names and shell expressions are not accepted as refs.

Using GitHub CLI on your own machine:

```bash
gh workflow run build-zlib.yml --repo whoisxy/Android-SDK-toolchain-arm64 \
  -f ref=v1.3.1

# The generic dispatcher selects the same shared build/release pipeline.
gh workflow run build.yml --repo whoisxy/Android-SDK-toolchain-arm64 \
  -f dependency=repo
```

A successful task creates a GitHub Release **in this repository** and attaches its
build archive and checksum file. Script/header distributions are labeled as such;
they do not claim to be newly compiled native executables.

The shared pipeline resolves the recipe and runner, builds without release write
credentials, passes artifacts to a separate publisher job, creates a draft release,
uploads and checks asset sizes, then publishes it. A failed upload leaves a draft
for inspection instead of publishing an incomplete release.

## Run locally

```bash
bash scripts/install-host-deps.sh
./task list

# Build and release, using credentials from your own environment.
export GITHUB_REPOSITORY=whoisxy/Android-SDK-toolchain-arm64
export GH_TOKEN=...  # supply through your own secret manager; never commit it
./task zlib v1.3.1

# The per-dependency entry point does the same thing.
tasks/zlib.sh v1.3.1

# Build an archive without publishing a release.
./task zlib v1.3.1 --build-only
```

Git, Python 3 and GitHub CLI (`gh`) are needed locally. The install script installs
Ubuntu build prerequisites; it does not configure GitHub credentials. Source build
subprocesses receive an environment with the standard GitHub token variables and
temporary Git authentication configuration removed. Upstream source executes as
your local user; CI's separate publisher job is the recommended release path.

Output goes to `dist/`; intermediate work uses `BUILD_ROOT` or `work/`. Set `JOBS`
to control compilation parallelism. No implicit cleanup removes unrelated files.

## Runner requirements

Most CMake, header and script tasks default to the GitHub-hosted `ubuntu-24.04`
runner. Provision these self-hosted runners before dispatching large tasks:

| Tasks | Labels | Storage and memory guidance |
|---|---|---|
| `skia`, `dart-sdk`, `flutter-tools`, Android engine tasks | `self-hosted`, `linux`, `x64`, `sdk-builder` | 100–150+ GiB free disk and 32+ GiB RAM for engine/SDK builds; the CLI cache task needs less |
| AOSP Android tool tasks | `self-hosted`, `linux`, `x64`, `aosp-builder` | At least 400 GiB free disk and 64+ GiB RAM; allow room for the platform checkout and build |

The optional workflow `runner` input accepts a JSON array of labels. An input such
as `["self-hosted","linux","x64","my-builder"]` overrides the recipe's runner.
The resource guard rejects insufficient disk space; it does not establish full
host compatibility. Build runners need outbound HTTPS for upstream sources,
toolchain bootstraps and package repositories.

Self-hosted jobs retain temporary source/build directories for inspection. Reclaim
completed job directories under the runner's temporary area using your retention
policy. These scripts do not automatically remove the full AOSP/SDK checkouts.

## What is implemented

The registry includes Android SDK tools, native libraries, GN/Ninja, `repo`,
`depot-tools`, Dart SDK, the Flutter CLI/tool snapshot and Android engine tasks.
See [docs/tasks.md](docs/tasks.md) for the exact recipe list and output kinds.

The broader source/package inventory is retained in
`inventory/source-dependencies.json`. **Inventory entries without a task are not
implemented standalone builds.** Upstream toolchain prebuilts and declared package
inputs are recorded separately from source-built outputs. This repository does not
claim to rebuild every compiler, JDK, Android runtime or third-party binary.

Optional refs change only the chosen dependency's source. Its declared dependency
recipes or AOSP platform manifest remain pinned. A substantially different upstream
version can require a recipe update; accepting a ref does not guarantee every
historical or future version will build with the same flags.

## Add or change a dependency

1. Add its source URL, default commit, backend, dependency graph and optional runner
   to `recipes/registry.json`.
2. Add a backend in `scripts/build.py` if it needs a new build system.
3. Run `python3 scripts/generate-tasks.py` to generate its Bash task, workflow and
   task-list documentation.
4. Run the manual verification workflow, then a selected build/release task.

To publish future dependencies to their own repositories, set each recipe's
`release_repository` and configure the optional `RELEASE_TOKEN` secret. No build
recipe changes or repository split are required. See [docs/releases.md](docs/releases.md).

## Verification gate

All workflows are **manual-only**. Pushes and pull requests do not start builds or
verification. Per the requested handoff, the initial source is pushed first and
verification waits for explicit approval. Recipe availability and a successful
push do not imply that all dependencies have completed a build.

## Licensing

New automation uses the MIT license in `LICENSE`. Dependency sources retain their
upstream licenses. Release archives carry available top-level notices and source
provenance; the inventory and copied notices are not a complete legal/SBOM review.
