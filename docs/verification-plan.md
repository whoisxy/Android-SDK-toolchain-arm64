# Verification handoff

All workflows have manual entry points. No workflow is triggered by a push or pull
request, so pushing the initial implementation does not start verification.

The initial handoff stops after pushing. The user must approve continuing before
local validation or Actions verification begins.

The proposed first pass is:

1. Dispatch **Verify task framework**: revision/credential-boundary tests, recipe
   graph checks, generated-task consistency, Bash syntax and actionlint.
2. Dispatch **Build and release zlib**, selecting the public upstream `v1.3.1` tag.
   Confirm that a native library archive and checksum appear in its release.
3. Dispatch **Build and release repo** and **Build and release depot-tools** with
   their default source pins. Confirm the interpreted-tool distribution assets.
4. Inspect Actions results and release assets; address observed failures before
   broadening the build set.

These runs create actual dependency releases, not placeholder permission-test
releases. Large AOSP, SDK and engine builds are not part of the first pass and
require their documented self-hosted runners. A successful representative pass is
not a claim that all 45 recipes have been built or tested on a device.
