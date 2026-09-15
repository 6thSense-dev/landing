# Contextual interval playback

Previously, requesting an idle interval without a matching recording preview silently opened the first available video and applied the interval offset. That could display unrelated footage.

Interval playback now requires an explicit finite nonnegative `clean_start_s` and exactly one output labelled `recording_preview` for the requested recording. Missing or ambiguous mapping shows an error and opens no replacement. The separate joined-footage action remains available. A later playback request supersedes an earlier response, and failed requests clear previous previews.

This validates selection consistency with the producer's supplied output labels. It does not independently validate media alignment, source-to-clean transformations or activity quality, and does not save human judgments or modify payment records. A richer source/output mapping contract remains necessary before source-time annotation editing.

Mocked Playwright tests exercise absent, ambiguous and missing-position mappings plus successful explicit matching on three viewport sizes. They do not verify production videos.
