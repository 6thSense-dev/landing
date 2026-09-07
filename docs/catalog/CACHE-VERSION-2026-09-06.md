# QA cache invalidation review repair

The camera-only QA change emits `not_applicable` instead of `not_run`, but the
initial candidate retained `6s-catalog-ingest/1.1.0`. Because that version is part
of the input hash, normal incremental ingest reused prior details before the new
grading code ran. A camera-only take could retain its old checks and grade.

Bump the pipeline to `6s-catalog-ingest/1.2.0`. This changes both provenance and
cache identity, using the existing cache convention. The next ingest recomputes
all prior-version takes; no live or published corpus was regenerated here.

`test_cache_version.py` creates a real prior-release cache hash and a scratch
camera-only take. Only the external video probe is substituted; file hashing,
cache decisions, clip assembly, QA and detail writes execute normally. Before
the bump it failed because the prior semantic cache was reused. After the bump
it verifies new `not_applicable` QA, updated provenance and replacement details.
A second unchanged ingest must reuse the new cache without probing or rewriting.

Validation: **163 passed** across cache, camera-only QA, ingest, fixture corpus,
benchmark, honesty and schema-sync tests on the existing Python 3.12 interpreter.
`git diff --check` passed. No database, provider, deployment, model, live catalog
or capture operation ran. The full application/build/browser gates were not
rerun for this Python version/cache-only repair.

Independent review of the new exact head remains pending. The PR stays draft.
The actual Railway auto-deploy/branch policy is still unverified, and backend
startup runs Alembic; no main merge or deployment is authorized by these tests.
