"""Consumer checks for disclosed recovery metadata already committed in Clean."""
import re

UNKNOWN_FIELDS = ('complete','start_time','clock_synced','stop_reason','received_frames',
                  'written_frames','dropped_frames','fw','lossless','truncated')


def _sources(rows):
    result = {}
    if not isinstance(rows,list) or not rows:
        raise ValueError('Reconstructed source inventory is missing')
    for row in rows:
        key = tuple(row.get(k) for k in ('bucket','key','version_id'))
        size = row.get('bytes',row.get('size_bytes'))
        sha = row.get('sha256','')
        if (any(not isinstance(k,str) or not k or k=='null' for k in key)
                or key in result or type(size) is not int or size<=0 or not re.fullmatch(r'[a-f0-9]{64}',sha)):
            raise ValueError('Reconstructed source identity or digest is invalid')
        result[key] = (size,sha)
    return result


def validate_reconstructed(metadata, provenance, recording, metadata_ref):
    recovery = recording.get('source_provenance',{}).get('metadata_recovery',{})
    ref = recovery.get('metadata',{})
    auth = recovery.get('authorization',{})
    if (provenance.get('schema')!='6thsense-clean-source-metadata/2'
            or provenance.get('copy_mode')!='reconstructed_from_verified_sources'
            or provenance.get('source_metadata')!=[] or provenance.get('reconstruction')!=recovery
            or recovery.get('scope')!='available_source_only' or recovery.get('capture_completeness')!='unknown'
            or auth.get('bucket')!='6thsense-deploy-artifacts'
            or not auth.get('key','').startswith('clean-plans/source-metadata-recovery/')
            or auth.get('version_id') in (None,'','null') or not re.fullmatch(r'[a-f0-9]{64}',auth.get('sha256',''))
            or ref.get('bucket')!='6thsense-processed' or not ref.get('key','').startswith('clean/')
            or ref.get('version_id') in (None,'','null')
            or any(ref.get(k)!=metadata_ref.get(k) for k in ('bytes','sha256'))
            or metadata.get('schema')!='6thsense-reconstructed-source-metadata/1'
            or metadata.get('metadata_origin')!='reconstructed'
            or metadata.get('recording_id')!=recording['recording']
            or metadata.get('device_id')!=recording['recording'].split('_')[-1]
            or metadata.get('capture_completeness')!='unknown'
            or recording.get('media',{}).get('capture_completeness')!='unknown'
            or any(k not in metadata or metadata[k] is not None for k in UNKNOWN_FIELDS)
            or metadata.get('inspection_scope')!='all_available_sources'
            or metadata.get('frame_count_scope')!='available_source_frames'
            or type(metadata.get('frame_count')) is not int or metadata['frame_count']<=0
            or metadata['frame_count']!=recording.get('media',{}).get('source_frame_count')
            or metadata.get('recovery_authorization')!=auth
            or metadata.get('calibration_provenance',{}).get('source')!=recording.get('calibration_source')
            or metadata.get('calibration_provenance',{}).get('mode')!='recovered_camera_calibration'):
        raise ValueError('Reconstructed metadata disclosure or provenance does not match Clean')
    if _sources(metadata.get('source_media')) != _sources(recording.get('sources')):
        raise ValueError('Reconstructed metadata source versions, sizes or hashes differ from Clean')
