import { cleanTotals, groupCleanFootage } from './opsCleanGroups.js';

const REGIONS = [['korea', 'Korea'], ['china', 'China'], ['vietnam', 'Vietnam'], ['india', 'India']];

export function cleanRegions(runs, collections) {
  const regions = new Map(REGIONS.map(([key, label]) => [key, { key, label, runs: [], collections: [] }]));
  const byRun = new Map();
  for (const run of runs) {
    const key = run.region?.key || 'unassigned';
    if (!regions.has(key)) regions.set(key, { key, label: run.region?.label || 'Needs region review', runs: [], collections: [] });
    regions.get(key).runs.push(run);
    byRun.set(run.run_id, key);
  }
  for (const collection of collections) {
    const keys = new Set((collection.source_runs || []).map(source => byRun.get(source.run_id)));
    // A viewing collection must be wholly contained in the selected region.
    if (keys.size === 1 && !keys.has(undefined)) regions.get([...keys][0]).collections.push(collection);
  }
  return [...regions.values()].map(region => ({
    ...region,
    totals: cleanTotals(region.runs),
    recordings: region.runs.reduce((count, run) => count + run.recording_count, 0),
    contributors: new Set(region.runs.map(run => run.wearer_id).filter(id => id != null)).size,
    businesses: new Set(region.runs.map(run => run.counterparty?.id).filter(Boolean)).size,
    cameras: new Set(region.runs.map(run => run.device_id)).size,
    groups: groupCleanFootage(region.runs, region.collections),
  }));
}
