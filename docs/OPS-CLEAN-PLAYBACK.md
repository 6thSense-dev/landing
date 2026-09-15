# Contextual playback in current Operations

Interval review requires a recording identity and an explicit finite nonnegative clean-video offset. Recording-level payment review starts the requested recording at zero and does not invent an interval offset.

A historical `recording_preview` is preferred; current multimodal output can use a unique `left_video`. Missing or ambiguous roles fail closed. Contextual playlists contain only that recording's preview/eye videos and do not automatically advance. Whole-batch and combined-collection playback remain separate, available paths.

Every play, renewal, close, file switch, contributor change and unmount invalidates older asynchronous requests as appropriate. Renewal requires the same key, role, recording, version and digest. A late request cannot reopen a closed player, replace a newer collection, or overwrite a manual eye-video selection.

Browser tests cover missing/ambiguous preview, missing offset, matching preview, stereo access, duplicate eye output, changed version refusal, deferred renewal/collection races, and actual decoding/seeking/playback of the existing synthetic WebM fixture. This does not verify production source-to-output alignment or physical clocks. Task declarations remain bound to decoded-source time, never inferred from edited-player time.
