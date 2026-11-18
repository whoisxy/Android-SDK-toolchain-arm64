# Setup status

The dependency task source, recipes, CLI and documentation are published here.
The 45 individual Actions entry points, generic/reusable build-release workflows
and manual verification workflow are prepared in a following local commit.

GitHub rejected workflow-file publication because the supplied fine-grained PAT
lacks Workflows read/write permission. Enable that repository permission for
whoisxy/Android-SDK-toolchain-arm64; Actions read/write is also needed to dispatch
workflows after the user approves verification. The same token can be updated;
it does not need to be pasted into the conversation again.

No verification, build or release workflow has been run. No secrets were created.
