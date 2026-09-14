import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanTotals, groupCleanFootage } from '../src/portal/opsCleanGroups.js';

const run = (overrides = {}) => ({ run_id: 'first', wearer_id: 1, device_id: '16A4A5', retained_seconds: 20297.806709, rejected_seconds: 9746.833299666667, source_seconds: 30044.640008666705, estimated_krw: 62021, paid: false, ...overrides });

test('two payable runs and their viewing collection become one contributor with no duplicate earnings', () => {
  const runs = [run(), run({ run_id: 'second', retained_seconds: 7975, rejected_seconds: 3266.9, source_seconds: 11241.9, estimated_krw: 24368 })];
  const collection = { collection_id: 'joined', wearer_id: 1, retained_seconds: 28272.8 };
  const before = structuredClone(runs);
  const groups = groupCleanFootage(runs, [collection]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].runs.length, 2);
  assert.deepEqual(groups[0].collections, [collection]);
  assert.equal(groups[0].totals.due, 86389);
  assert.equal(Math.round(groups[0].totals.kept), 28273);
  assert.equal(Math.round(groups[0].totals.excluded), 13014);
  assert.equal(Math.round(groups[0].totals.source), 41287);
  assert.deepEqual(runs, before);
});

test('groups by contributor identity across cameras and leaves other contributors separate', () => {
  const groups = groupCleanFootage([run(), run({ run_id: 'other-camera', device_id: 'ABC123' }), run({ run_id: 'other-person', wearer_id: 2 })], []);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].runs.length, 2);
  assert.equal(groups[1].wearer_id, 2);
});

test('unassigned cameras remain separate and a viewing-only collection adds no estimate', () => {
  const groups = groupCleanFootage([run({ wearer_id: null }), run({ wearer_id: null, device_id: 'ABC123' })], [{ collection_id: 'view', wearer_id: 2, retained_seconds: 9999 }]);
  assert.equal(groups.length, 3);
  assert.equal(groups[2].totals.kept, 0);
  assert.equal(groups[2].totals.due, 0);
});

test('unpaid balance excludes paid runs and does not present unknown rates as a complete total', () => {
  const totals = cleanTotals([run({ paid: true }), run({ estimated_krw: 24368 }), run({ estimated_krw: null })]);
  assert.equal(totals.due, 24368);
  assert.equal(totals.missing, true);
  assert.equal(cleanTotals([run({ paid: true, estimated_krw: null })]).missing, false);
  assert.deepEqual(cleanTotals([]), { kept: 0, excluded: 0, source: 0, due: 0, missing: false });
});
