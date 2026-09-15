export function cleanTotals(runs) {
  return runs.reduce((total, run) => ({
    kept: total.kept + run.retained_seconds,
    excluded: total.excluded + run.rejected_seconds,
    source: total.source + run.source_seconds,
    due: total.due + (!run.counterparty && !run.paid ? run.estimated_krw ?? 0 : 0),
    missing: total.missing || (!run.counterparty && !run.paid && run.estimated_krw == null),
  }), { kept: 0, excluded: 0, source: 0, due: 0, missing: false });
}

// Collections provide playback only. All time and money come from source runs.
export function groupCleanFootage(runs, collections) {
  const groups = new Map();
  const ensure = (key, wearerId, counterparty = null) => {
    if (!groups.has(key)) groups.set(key, { key, wearer_id: wearerId, counterparty, runs: [], collections: [] });
    return groups.get(key);
  };
  for (const run of runs) {
    const key = run.counterparty ? `business:${run.counterparty.id}` : run.wearer_id == null ? `unassigned:${run.device_id}` : `wearer:${run.wearer_id}`;
    ensure(key, run.wearer_id, run.counterparty).runs.push(run);
  }
  for (const collection of collections) {
    const key = collection.wearer_id == null ? `collection:${collection.collection_id}` : `wearer:${collection.wearer_id}`;
    ensure(key, collection.wearer_id).collections.push(collection);
  }
  return [...groups.values()].map(group => ({ ...group, totals: cleanTotals(group.runs) }));
}
