# Catalog tier buckets — round 1 response

| Finding | Commit | Verification |
|---|---|---|
| [B] Correct operator values, rollout order, and rollback-first env restoration | `12fa063` | documentation value/stale-path checks |
| [M] Make code-only deploy package defaults a no-op | `340d300` | default and explicit config tests; unsafe-default mutation went red |
| [M] Allow both new buckets in all three CSP directives | `5067dde` | directive-by-directive host assertion |
| [M] Expose package settings and probe a known package object in staff health | `5b42822` | stubbed success/AccessDenied tests plus API health test; skipped-head mutation went red |
| [M] Route `archives/` to `<package_prefix>_archives/` | `309bb55` | archive signing test; catalog-bucket mutation went red |
| [L] Treat blank package env as unset and cache-key both settings | `923ee5c` | blank/whitespace and signature tests; both mutations went red |
| [L] Replace stale tier URLs and remove nonexistent API route | `de0673e` | stale URL/route scan |

## Final gate

```text
$ python3 -m pytest backend/tests/test_catalog_store.py backend/tests/test_catalog_upload_bundle.py backend/tests/test_catalog_api.py -q -p no:cacheprovider
104 passed, 58 warnings in 14.68s
```

Docker/testcontainers was available; no tests were skipped as environment-blocked.

## Mutation proof

- Hardcoded processed defaults and unsafe blank handling: `3 failed`.
- Skipped package head, catalog-routed archives, and deleted package fields from the cache
  signature: `4 failed`.
- Restored combined targeted run: `7 passed`.

## Adversarial review

Attacked blank/whitespace config, empty and malformed manifest clip summaries, failed package
heads, traversal, local mode, cache invalidation, CSP host coverage, and stale docs. This found
and fixed one stale README preview-bucket sentence. The existing same-region assumption remains:
both live tiers are `us-west-2`; no package-region variable was requested.

## Demo

```text
code-only: 6thsense-catalog-media v2/media/
posters/clip.jpg -> 6thsense-catalog/v2/posters/clip.jpg
media/clip/video/left.mp4 -> 6thsense-processed/imported/2026-08-24_nervous-1/clip/video/left.mp4
archives/clip.tar.gz -> 6thsense-processed/imported/2026-08-24_nervous-1/_archives/clip.tar.gz
```
