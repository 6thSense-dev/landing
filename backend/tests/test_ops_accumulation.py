"""Country totals must not multiply stereo media or lose processed recordings."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.ops_accumulation import accumulated_data


def episode(recording='one', country='india', **overrides):
    values = dict(recording=recording, device_id='ABC123', session=f'{country}-work',
                  prefix=f'sessions/{country}-work/ABC123/{recording}/', wearer_id=None,
                  duration_s=3600, size_bytes=1_000_000_000, deleted_at=None)
    return SimpleNamespace(**(values | overrides))


def registry_for(ep, country='india'):
    return {ep.recording: dict(recording=ep.recording, device_id=ep.device_id, session=ep.session,
                              counterparty=dict(kind='business', id='example', name='Private source',
                                                country=country, payment_model='b2b_contract'))}


def rows(summary):
    return {row['country']: row for row in summary['countries']}


def test_accumulation_counts_processed_and_pending_once_despite_stereo_or_redelivery():
    processed, pending = episode('processed'), episode('pending', duration_s=1800)
    deleted = episode('deleted', deleted_at=datetime.now(timezone.utc))
    inventory = {'pending': {'prefixes': [pending.prefix, pending.prefix],
                             'media': [{'key': pending.prefix + eye, 'bytes': 1} for eye in ('left.mp4', 'right.mp4')]}}
    result = accumulated_data([processed, pending, deleted], {}, inventory)
    assert result['totals'] == dict(episodes=2, known_seconds=5400, unknown_duration_episodes=0,
                                    uploaded_bytes=2_000_000_000, unknown_size_episodes=0)
    assert rows(result)['india']['episodes'] == 2
    assert rows(result)['vietnam']['episodes'] == 0
    assert len(result['countries']) == 4


def test_registered_company_resolves_unlabelled_upload_and_trial_country():
    ep = episode(country='trial')
    result = accumulated_data([ep], registry_for(ep), {})
    assert rows(result)['india']['known_seconds'] == 3600
    assert 'test' not in rows(result)
    assert 'Private source' not in str(result) and 'ABC123' not in str(result)


@pytest.mark.parametrize('conflict', ['business', 'source', 'identity', 'owner'])
def test_conflicting_country_or_business_identity_stays_unassigned(conflict):
    ep = episode()
    registry = registry_for(ep)
    inventory = {}
    if conflict == 'business':
        registry[ep.recording]['counterparty']['country'] = 'china'
    elif conflict == 'source':
        inventory[ep.recording] = {'prefixes': ['sessions/korea-work/ABC123/one/']}
    elif conflict == 'identity':
        registry[ep.recording]['device_id'] = 'FFFFFF'
    else:
        ep.wearer_id = 5
    result = accumulated_data([ep], registry, inventory)
    assert rows(result)['unassigned']['episodes'] == 1
    assert rows(result)['india']['episodes'] == 0


@pytest.mark.parametrize('duration', [None, 0, -1, float('nan'), float('inf'), True, '3600'])
def test_missing_or_invalid_duration_is_counted_without_inventing_hours(duration):
    result = accumulated_data([episode(duration_s=duration)], {}, {})
    assert result['totals']['known_seconds'] == 0
    assert result['totals']['unknown_duration_episodes'] == 1
    assert result['totals']['uploaded_bytes'] == 1_000_000_000


def test_unknown_country_test_footage_and_unknown_size_reconcile_with_grand_total():
    result = accumulated_data([episode('unknown', country='unknown', size_bytes=0),
                               episode('test', country='trial'), episode('kr', country='korea')], {}, {})
    groups = rows(result)
    assert groups['unassigned']['episodes'] == groups['test']['episodes'] == groups['korea']['episodes'] == 1
    assert result['totals']['unknown_size_episodes'] == 1
    for field, value in result['totals'].items():
        assert sum(row[field] for row in result['countries']) == value


def test_empty_ledger_reports_zero_for_every_supported_country():
    result = accumulated_data([], {}, {})
    assert len(result['countries']) == 4
    assert all(value == 0 for value in result['totals'].values())
