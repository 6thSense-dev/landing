"""Accumulated capture totals from the durable episode ledger, once per recording."""
import math

from app.core.ops_regions import REGIONS, clean_region
from app.core.ops_sources import business_source


def accumulated_data(episodes, registry, inventory):
    """Include processed/held uploads; exclude deleted rows and derivative copies.

    Stored upload bytes are not current S3 storage usage. Country comes from
    confirmed business provenance and preserved source paths, never a profile.
    """
    labels = {**REGIONS, 'test': 'Test footage', 'unassigned': 'Unassigned country'}
    groups = {key: dict(country=key, label=label, episodes=0, known_seconds=0,
                        unknown_duration_episodes=0, uploaded_bytes=0,
                        unknown_size_episodes=0)
              for key, label in labels.items()}
    for episode in episodes:
        if episode.deleted_at is not None:
            continue
        prefixes = set(inventory.get(episode.recording, {}).get('prefixes', []))
        if episode.prefix:
            prefixes.add(episode.prefix)
        sources = [{'key': prefix} for prefix in sorted(prefixes)]
        doc = {'recordings': [{'sources': sources}]}
        try:
            party = business_source(episode, registry)
            if party:
                doc['country'] = party['country']
            country = clean_region(doc)['key']
        except ValueError:
            # Conflicting business provenance must not fall back to a guessed country.
            country = 'unassigned'
        group = groups[country]
        group['episodes'] += 1
        duration = episode.duration_s
        if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                and math.isfinite(duration) and duration > 0):
            group['known_seconds'] += duration
        else:
            group['unknown_duration_episodes'] += 1
        size = episode.size_bytes
        if isinstance(size, int) and not isinstance(size, bool) and size > 0:
            group['uploaded_bytes'] += size
        else:
            group['unknown_size_episodes'] += 1
    totals = {field: sum(row[field] for row in groups.values()) for field in (
        'episodes', 'known_seconds', 'unknown_duration_episodes',
        'uploaded_bytes', 'unknown_size_episodes')}
    for row in [*groups.values(), totals]:
        row['known_seconds'] = round(row['known_seconds'], 3)
    return {'basis': 'non_deleted_episode_ledger', 'totals': totals,
            'countries': [row for key, row in groups.items() if key in REGIONS or row['episodes']]}
