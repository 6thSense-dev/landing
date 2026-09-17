export const processingLabels = {
  unknown: "Awaiting scan",
  unavailable: "Source not listed",
  uploading: "Uploading",
  queued: "Queued",
  recovering: "Recovery needed",
  running: "Processing",
  retry: "Retry pending",
  blocked: "Blocked",
  rejected: "Rejected",
  clean: "In Clean",
  awaiting_verification: "Checking source match",
};

export function processingState(episode) {
  if (episode.deleted_at) return "rejected";
  const state = episode.processing?.state;
  // Only receipt reconciliation can complete an imported result. A run ID alone
  // says nothing about newly uploaded or replaced Raw files.
  if (state === "awaiting_verification" && episode.raw?.status === "processed"
      && episode.raw.pending_files === 0) return "clean";
  return state || (episode.raw?.status === "processed" ? "clean"
    : episode.raw?.status === "unavailable" ? "unavailable" : "unknown");
}

const causes = [
  [/original metadata missing|source metadata missing/i, "Metadata missing",
    "Recover the original metadata for this recording, then revalidate it."],
  [/metadata could not be read|malformed metadata/i, "Metadata unreadable",
    "Check access to the metadata and recover a readable original."],
  [/capture completion not confirmed|missing.*completion evidence/i, "Recording incomplete",
    "Confirm the recording finished and its final files and metadata were uploaded."],
  [/new source versions arrived|source versions differ|source (?:versions? |set )?changed/i, "Source files changed",
    "Compare the updated upload with the earlier processing attempt before retrying."],
  [/uncertain batch submission|duplicate batch submissions|batch job not returned/i, "Job status uncertain",
    "Confirm whether the cloud job exists or is still running before submitting another."],
  [/conflicting imu measurements/i, "IMU data conflict",
    "Recover a consistent sensor timeline from the source before processing."],
  [/source calibration missing/i, "Calibration missing",
    "Recover the calibration for the camera used in this recording."],
  [/conflicting camera calibrations|invalid calibration|calibration.*mismatch/i, "Calibration mismatch",
    "Check that the calibration belongs to this camera and matches the recording."],
  [/assign the source camera|attribution required|business attribution|confirmed source country required/i, "Source attribution needed",
    "Confirm the contributor or business and capture country before processing."],
  [/contributor account deletion requested/i, "Account deletion pending",
    "Resolve the contributor deletion request before processing this source."],
  [/worker retry limit reached/i, "Retry limit reached",
    "Inspect the recorded failure and fix its cause before retrying."],
  [/no technically valid retained segment/i, "No valid segments",
    "Review the timing and quality exclusions to see whether source recovery is possible."],
  [/shared inference budget reached/i, "Model budget reached",
    "Review the remaining work and processing budget before resuming."],
  [/authorized (?:inference|cloud processing) window ended/i, "Run window ended",
    "Review the remaining work and renew the cloud run window to resume."],
  [/source conversion failed/i, "Conversion failed",
    "Inspect the conversion job's error before retrying."],
  [/clean extraction failed/i, "Clean processing failed",
    "Inspect the Clean job's error before retrying."],
];

export function processingPresentation(episode) {
  const state = processingState(episode);
  const result = { state, label: processingLabels[state] || "Unknown status", nextStep: "" };
  if (state === "awaiting_verification") {
    result.nextStep = "The Clean result is imported. Automatic scans check that it covers the exact Raw files before marking this recording In Clean.";
  } else if (state === "clean") {
    result.nextStep = "Verified Clean output covers the current Raw source files.";
  } else if (["blocked", "retry", "recovering"].includes(state)) {
    const cause = causes.find(([pattern]) => pattern.test(episode.processing?.reason || ""));
    if (cause) [, result.label, result.nextStep] = cause;
    else result.nextStep = "Review the reported reason before retrying; the source remains preserved.";
  }
  return result;
}
