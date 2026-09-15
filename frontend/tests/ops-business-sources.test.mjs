import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanTotals, groupCleanFootage } from '../src/portal/opsCleanGroups.js';
import { cleanRegions } from '../src/portal/opsCleanRegions.js';
import { regionOfEpisode, sourceKey } from '../src/portal/opsShared.js';

const business = { kind: 'business', id: 'factory-example', name: 'Example factory', country: 'china', payment_model: 'b2b_contract' };
const run = (id, overrides = {}) => ({ run_id: id, wearer_id: null, device_id: 'ABC123', counterparty: business,
  region: { key: 'china', label: 'China' }, retained_seconds: 60, rejected_seconds: 40, source_seconds: 100,
  estimated_krw: null, paid: false, recording_count: 1, ...overrides });

test('business batches merge by business identity without merging unassigned or individual footage', () => {
  const groups = groupCleanFootage([run('first'), run('second', { device_id: 'FFFFFF' }),
    run('other-business', { counterparty: { ...business, id: 'other-factory' } }),
    run('unassigned', { counterparty: null }), run('individual', { counterparty: null, wearer_id: 1, estimated_krw: 183 })], []);
  assert.equal(groups.length, 4);
  const factory = groups.find(g => g.key === 'business:factory-example');
  assert.deepEqual(factory.runs.map(r => r.run_id), ['first', 'second']);
  assert.equal(factory.counterparty, business);
  assert.deepEqual(factory.totals, { kept: 120, excluded: 80, source: 200, due: 0, missing: false });
  assert.equal(groups.find(g => g.key === 'wearer:1').totals.due, 183);
});

test('business hours count in China while business rows cannot inflate personal money or missing-rate warnings', () => {
  const runs = [run('first'), run('second', { estimated_krw: 999999 }),
    run('individual', { counterparty: null, wearer_id: 1, estimated_krw: 183 })];
  const regions = cleanRegions(runs, []);
  const china = regions.find(r => r.key === 'china');
  assert.equal(china.businesses, 1);
  assert.equal(china.contributors, 1);
  assert.equal(china.recordings, 3);
  assert.equal(china.totals.kept, 180);
  assert.equal(china.totals.due, 183);
  assert.equal(china.totals.missing, false);
  assert.equal(regions.find(r => r.key === 'korea').totals.source, 0);
  assert.equal(cleanTotals([run('first')]).missing, false);
});

test('Raw uses explicit business country over Trial and separates business/person filter identities', () => {
  const source = { counterparty: business, session: '2026-09-01_Trial', wearer_id: null };
  assert.equal(regionOfEpisode(source), 'China');
  assert.equal(sourceKey(source), 'business:factory-example');
  assert.equal(sourceKey({ wearer_id: 1 }), 'wearer:1');
  assert.notEqual(sourceKey({ counterparty: { ...business, id: '1' } }), sourceKey({ wearer_id: 1 }));
});
