import test from 'node:test';
import assert from 'node:assert/strict';
import { processingLabels, processingPresentation, processingState } from '../src/portal/rawProcessingStatus.js';

const episode = (state, reason = '', raw = { status: 'pending', pending_files: 1 }) => ({
  recording: 'ego_status_example',
  processing: { state, reason, result_run_id: 'a-produced-run-is-not-verification' },
  raw,
});

test('a result run or incomplete source receipts cannot turn verifying output into Clean', () => {
  const incomplete = [
    undefined,
    { status: 'partial', pending_files: 1 },
    { status: 'partial', pending_files: 0 },
    { status: 'pending', pending_files: 0 },
    { status: 'processed', pending_files: 1 },
    { status: 'processed' },
    { status: 'processed', pending_files: null },
    { status: 'processed', pending_files: '0' },
  ];
  for (const raw of incomplete) {
    const row = episode('awaiting_verification');
    row.raw = raw;
    assert.equal(processingState(row), 'awaiting_verification', JSON.stringify(raw));
    const display = processingPresentation(row);
    assert.equal(display.state, 'awaiting_verification');
    assert.equal(display.label, processingLabels.awaiting_verification);
  }
});

test('complete source verification can resolve awaiting verification without mutating backend state', () => {
  const row = episode('awaiting_verification', 'Worker output is awaiting verification.', {
    status: 'processed', pending_files: 0,
  });
  const before = structuredClone(row);
  assert.equal(processingState(row), 'clean');
  const display = processingPresentation(row);
  assert.equal(display.state, 'clean');
  assert.equal(display.label, processingLabels.clean);
  assert.deepEqual(row, before);
});

test('verified receipts cannot override business holds or other explicit processing states', () => {
  const cases = [
    ['blocked', 'Contributor or business attribution required'],
    ['blocked', 'Contributor account deletion requested.'],
    ['running', 'AWS Clean extraction running or queued.'],
    ['queued', 'Waiting for a worker'],
    ['recovering', 'Source media is missing.'],
    ['retry', 'Worker retry required'],
    ['rejected', 'Operator rejected this source'],
  ];
  for (const [state, reason] of cases) {
    const row = episode(state, reason, { status: 'processed', pending_files: 0 });
    assert.equal(processingState(row), state, reason);
    assert.equal(processingPresentation(row).state, state, reason);
  }
});

test('deleted takes remain rejected regardless of worker state, cause text, or verified receipts', () => {
  for (const state of ['awaiting_verification', 'clean', 'blocked', 'running']) {
    const row = {
      ...episode(state, 'Original metadata missing', { status: 'processed', pending_files: 0 }),
      deleted_at: '2026-09-17T01:00:00Z',
    };
    assert.equal(processingState(row), 'rejected');
    const display = processingPresentation(row);
    assert.equal(display.state, 'rejected');
    assert.equal(display.label, processingLabels.rejected);
  }
});

test('generic technical failures do not invent metadata or scene diagnoses', () => {
  for (const reason of [
    'Clean extraction failed: AssertionError',
    'Source conversion failed: Essential container in task exited',
    'RuntimeError',
  ]) {
    const row = episode('blocked', reason);
    const display = processingPresentation(row);
    assert.equal(display.state, 'blocked');
    assert.doesNotMatch(`${display.label} ${display.nextStep}`, /metadata|scene|hands?\s+(?:absent|missing|out)/i, reason);
    assert.equal(row.processing.reason, reason);
  }
});

test('an unknown backend diagnostic retains a generic presentation and the untouched diagnostic', () => {
  const reason = 'Unrecognized worker condition: custom stage returned E_UNEXPECTED';
  const row = episode('blocked', reason);
  const before = structuredClone(row);
  const display = processingPresentation(row);
  assert.equal(display.state, 'blocked');
  assert.equal(display.label, processingLabels.blocked);
  assert.doesNotMatch(`${display.label} ${display.nextStep}`, /metadata|scene|IMU|calibration/i);
  assert.deepEqual(row, before);
});

test('known backend evidence produces the corresponding diagnosis and a relevant next step', () => {
  const cases = [
    ['Original metadata missing', 'Metadata missing', /recover.*metadata/i],
    ['New source versions arrived during processing; review before supersession', 'Source files changed', /compare.*upload/i],
    ['Uncertain Batch submission; manual reconciliation required before retry', 'Job status uncertain', /confirm.*(?:job|running)/i],
    ['Conflicting IMU measurements require source recovery', 'IMU data conflict', /consistent sensor timeline/i],
    ['No technically valid retained segment', 'No valid segments', /timing and quality exclusions/i],
  ];
  for (const [reason, label, nextStep] of cases) {
    const display = processingPresentation(episode('blocked', reason));
    assert.equal(display.state, 'blocked', reason);
    assert.equal(display.label, label, reason);
    assert.match(display.nextStep, nextStep, reason);
  }
  const uncertain = processingPresentation(episode('blocked', cases[2][0]));
  assert.doesNotMatch(uncertain.nextStep, /^\s*(?:retry|resubmit)\b/i);
  const empty = processingPresentation(episode('blocked', cases[4][0]));
  assert.doesNotMatch(`${empty.label} ${empty.nextStep}`, /hands?\s+(?:absent|missing|out)|phone use|computer use|metadata missing/i);
});

test('specific evidence takes priority over the generic failed-job wrapper', () => {
  const cases = [
    ['Clean extraction failed: Original metadata missing', 'Metadata missing', /recover.*metadata/i],
    ['Clean extraction failed: Authorized cloud processing window ended; originals preserved', 'Run window ended', /renew.*window/i],
    ['Clean extraction failed: Shared inference budget reached', 'Model budget reached', /review.*budget/i],
    ['Source conversion failed: Authorized cloud processing window ended; originals preserved', 'Run window ended', /renew.*window/i],
    ['Source conversion failed: Initial authorized compute window ended; archived originals preserved', 'Run window ended', /renew.*window/i],
  ];
  for (const [reason, label, nextStep] of cases) {
    const display = processingPresentation(episode('blocked', reason));
    assert.equal(display.state, 'blocked', reason);
    assert.equal(display.label, label, reason);
    assert.match(display.nextStep, nextStep, reason);
  }
});

test('a stale diagnostic cannot relabel an active or completed processing state as a new failure', () => {
  for (const state of ['running', 'awaiting_verification', 'clean']) {
    const display = processingPresentation(episode(state, 'Original metadata missing'));
    assert.equal(display.state, state);
    assert.equal(display.label, processingLabels[state]);
  }
});

for (const [reason, label] of [
  ["QA review required: no frames retained (uncertain_scene).", "Scene review required"],
  ["QA rejected: no frames retained (phone_use).", "Rejected by scene QA"],
  ["Clean extraction failed: Inference reservation contention", "Budget update interrupted"],
  ["Source conversion failed: Host EC2 (instance) terminated.", "Cloud worker interrupted"],
  ["Clean extraction failed: HTTP Error 500", "Model service interrupted"],
  ["Clean extraction failed: Unexpected or duplicate scene sample", "Scene response invalid"],
]) {
  test(`specific recovery cause: ${label}`, () => {
    assert.equal(processingPresentation({ processing: { state: "blocked", reason } }).label, label);
  });
}
