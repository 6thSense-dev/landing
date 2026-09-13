# Task activity review declarations

Operations → Clean → Review task activity opens an additive review form tied to an imported QC run. Enter a task identifier and load its latest review. Supply explicit criteria/version and source-timeline intervals with accepted, excluded or unknown judgments and reasons. Saving creates a complete replacement snapshot for that task; uncovered time is unknown. Previous revisions are retained by the backend.

This is a human declaration, not automated quality certification. The manifest supplies decoded source durations and object references. Source validation, physical clock identity and clean-video-to-source alignment remain unknown. Do not read edited clean-video positions as source positions without mapping evidence. This feature neither crops media nor establishes unique corpus usable hours. Review criteria must be explicit; no hand-detection, camera-quality or activity threshold is invented.

The UI converts decimal seconds to integer nanosecond strings without floating-point rounding. Duration summaries union overlapping declarations of the same judgment within each recording. Conflicting judgments are rejected. Cross-camera unique usable time remains null. Missing review accepted/excluded time is unknown, not zero. Original declarations and their reasons remain in history.

Review records bind the imported manifest digest, source references/durations, task, criteria and authenticated reviewer. Stale revisions or manifests conflict instead of overwriting another review. Criteria versions cannot silently change meaning. Task identities retain separate revision histories. The API offers historical revision reads; the initial UI edits the latest revision only.

This adds a table/migration in a PR; no production migration is applied. Existing manifests, raw footage, assignments, rates, approvals, paid flags, annotation judgments and dataset acceptance are not changed. Review duration does not reprice an agreement. Actual agreement terms and transfer evidence remain separate dependencies.

Tests use synthetic declarations and a disposable database or mocked browser APIs. They cannot establish production source integrity or reviewer correctness.
