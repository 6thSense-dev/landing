# QC source-time boundaries

The clean manifest validator rejects interval starts or ends outside `[0, recording.source_seconds]`. Existing 20ms partition and 50ms summary/end rounding tolerances are preserved for producer compatibility, but cannot authorize negative source time or an endpoint beyond the declared source. No value is clamped, rounded or repaired.

Previously, a one-second recording with `keep [-0.01, 1]` and retained total `1.01` passed both tolerances. It now fails validation. Exact zero/start and source-end boundaries remain valid. Zero-duration recordings with no intervals are valid; zero-length intervals remain invalid.

Malformed arrays, rows, duration values, source pins and output references now produce `ValueError` within validation. Boolean durations are not numeric durations. This preserves the existing importer's per-run failure isolation: invalid QC evidence is skipped and reported, while unrelated valid runs may still import. No existing database records are migrated or rewritten.

These checks establish declared time bounds, not actual media duration, task usefulness or unique usable hours. Existing interior rounding tolerances still permit small gaps/overlaps; a future exact source-time review contract must address that separately. Collector credit, rates, payment history and source objects are unchanged.

Synthetic verification: `python -m pytest backend/tests/test_ops_clean_time_bounds.py backend/tests/test_ops_clean.py -q`.
