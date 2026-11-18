# Source dependency inventory

`source-dependencies.json` retains the original 299 declared source/package inputs:
82 Git entries, 36 CIPD entries, 169 Dart package entries and 12 bundled Java/Maven
coordinates. Paths and upstream project names remain as provenance.

Every row is classified:

- `recipe-implemented`: associated with an executable task in the new registry.
- `upstream-prebuilt-input`: a declared CIPD package, not automatically source-built.
- `catalog-only`: retained context without a standalone recipe.

`recipes/registry.json` is authoritative for runnable tasks and default commits.
It additionally declares independent host and AOSP tool sources that were not
separate source checkouts in the original catalog. Some tasks intentionally use a
canonical upstream repository instead of the original downstream mirror; for example,
zlib uses `madler/zlib` so its upstream release tags can be selected directly.

The inventory is a record of declared inputs, not a fully resolved component-level
SBOM or proof that every task has completed a successful build.
