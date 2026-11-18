# Releases, destinations and secrets

## Current layout

Every task publishes its output to the repository running the workflow. Each run
gets a separate release tag:

```text
DEPENDENCY/linux-x86_64/SOURCE_COMMIT-RUN_ID-ATTEMPT
```

The requested tag/hash and full resolved source commit appear in the release notes
and the archive's build metadata. Source revision and pipeline repository revision
are recorded separately. The release archive contains installed output, declared
dependency output where needed, available license files and build metadata.

The pipeline creates the release as a draft, streams the archive and `.sha256`
sidecar using `gh`, checks the uploaded asset names/sizes, then publishes it. A failure
retains the draft for diagnosis. Reruns have distinct tags rather than silently
overwriting someone else's release assets.

## Credentials for this repository

Publishing to this same repository uses the automatically issued **`GITHUB_TOKEN`**
with `contents: write` in the release job. The build job has only read access and
does not receive `RELEASE_TOKEN` in its environment. Checkout credentials are not
persisted. No personal access token is required as a repository secret for this flow.

The personal access token used during initial setup is supplied only to the setup
process through hidden stdin and short-lived process environment. It is not included
in tracked files, Git remote URLs, generated manifests, artifacts or release notes.
It is not stored as an Actions secret by this setup.

The PAT used to push workflow files must permit repository **Contents: read/write**
and **Workflows: read/write** for this repository. Dispatching verification/build
workflows additionally requires **Actions: read/write**. GitHub's API does not offer
a complete introspection list of fine-grained PAT grants; actual operations establish
which capabilities are usable. GitHub's repository `permissions` object describes
the user's role and does not alone prove each PAT grant.

## Future per-dependency release repositories

Set a destination on a recipe:

```json
{
  "release_repository": "whoisxy/dependency-zlib"
}
```

Alternatively, use the workflow's `release_repository` input for one run. The
destination must already exist and have an initialized default branch. The pipeline
does not create, rename or change the visibility of destination repositories.

Add **`RELEASE_TOKEN`** as a repository or organization Actions secret with Contents
read/write access to the selected destination repositories. The release job uses it
only for a different destination; current-repository releases continue to use the
automatic token. Do not put a token in the registry, workflow inputs or repository
variables. The optional secret is not needed or created during initial setup.

## Can secrets be retrieved later?

GitHub Actions secret values are **write-only** through the UI and API: names and
metadata can be listed, but stored plaintext cannot be read back. Keep a copy in
your own password manager when you create a secret. Rotate a value if it is lost.

`GITHUB_TOKEN` is ephemeral and generated for each workflow run; it is not a newly
stored long-lived secret for the user to retrieve. This setup creates no new secret
values, so there are no generated secret values to hand back.
