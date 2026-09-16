import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanRegions } from '../src/portal/opsCleanRegions.js';

const run = (id, region, wearer = 1) => ({ run_id: id, region: { key: region, label: region }, wearer_id: wearer, device_id: `camera-${id}`, source_seconds: 7200, retained_seconds: 5400, rejected_seconds: 1800, recording_count: 2 });

test('multiple people in one region aggregate hours once, without adding joined copies', () => {
  const regions = cleanRegions([run('a', 'korea'), run('b', 'korea', 2), run('c', 'china')], [{ collection_id: 'joined', wearer_id: 1, retained_seconds: 999999, source_runs: [{ run_id: 'a' }] }]);
  const korea = regions.find(r => r.key === 'korea');
  assert.equal(korea.totals.kept, 10800);
  assert.equal(korea.totals.source, 14400);
  assert.equal(korea.contributors, 2);
  assert.equal(korea.recordings, 4);
  assert.equal(korea.groups.length, 2);
  assert.equal(regions.find(r => r.key === 'vietnam').totals.kept, 0);
});

test('same contributor in two regions keeps batches and combined playback inside each region', () => {
  const regions = cleanRegions([run('a', 'korea'), run('b', 'china')], [{ collection_id: 'mixed', wearer_id: 1, source_runs: [{ run_id: 'a' }, { run_id: 'b' }] }, { collection_id: 'missing', wearer_id: 1, source_runs: [{ run_id: 'gone' }] }]);
  assert.equal(regions.find(r => r.key === 'korea').groups[0].runs.length, 1);
  assert.equal(regions.find(r => r.key === 'china').groups[0].runs[0].run_id, 'b');
  assert.ok(regions.every(r => r.collections.length === 0));
});

test('missing provenance never uses a person or camera to guess geography', () => {
  const regions = cleanRegions([{ ...run('a', 'korea'), region: undefined, wearer_id: null }], []);
  assert.equal(regions.find(r => r.key === 'korea').recordings, 0);
  assert.equal(regions.find(r => r.key === 'unassigned').totals.kept, 5400);
  assert.equal(regions.find(r => r.key === 'unassigned').contributors, 0);
});
