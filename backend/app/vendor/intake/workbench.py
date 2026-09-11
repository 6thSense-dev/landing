"""Read-only activity projection and native C10 proposed revision exports."""
from copy import deepcopy
from fractions import Fraction
import json
import re
from app.vendor.intake.selections import digest, evaluate_selection, fields, ids, integer, sha, text, validate_json, covered, union, interval
from app.vendor.intake.revisions import revise_selection


def parse(raw):
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result: raise ValueError('duplicate JSON member')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    validate_json(value)
    return value


def preview_digest(value):
    return digest(value)


def _preview(candidate, current):
    supplied=candidate['preview']
    if supplied is None: return dict(status='unknown',reason='preview_not_supplied',frames=[])
    fields(supplied,{'report','asset','source_binding'})
    report=supplied['report'];asset=fields(supplied['asset'],{'path','content_sha256'})
    text(asset['path']);sha(asset['content_sha256'])
    # Paths pass the existing strict server asset validator too.
    if not re.fullmatch(r'[A-Za-z0-9_./-]+\.(mp4|webm)',asset['path']) or any(p in ('','..','.') for p in asset['path'].split('/')):
        raise ValueError('unsafe preview path')
    binding=fields(supplied['source_binding'],{'segment_id','source_ref','source_sha256','evidence_ids'})
    text(binding['segment_id']);sha(binding['source_sha256']);ids(binding['evidence_ids'])
    if type(report) is not dict or report.get('schema_version')!='intake-source-preview/v1': raise ValueError('unsupported preview report')
    sha(report.get('report_sha256'))
    if report['report_sha256']!=preview_digest({k:v for k,v in report.items() if k!='report_sha256'}): raise ValueError('preview report changed')
    if report.get('status')!='generated' or report.get('synthetic') is not current['synthetic']: raise ValueError('preview provenance conflict')
    for key in ('source_sha256','mapping_sha256','request_sha256'): sha(report.get(key))
    encoding=report.get('encoding',dict(codec='h264',container='mp4',profile='h264_mp4'))
    allowed=[dict(codec='h264',container='mp4',profile='h264_mp4'),dict(codec='vp9',container='webm',profile='vp9_webm')]
    if encoding not in allowed or report.get('video',{}).get('path')!='preview.'+encoding['container'] or not asset['path'].endswith('.'+encoding['container']): raise ValueError('preview codec/container conflict')
    if report.get('video',{}).get('sha256')!=asset['content_sha256']: raise ValueError('preview video pin conflict')
    source=next((s for s in current['timeline_report']['source_input']['segments'] if s['segment_id']==binding['segment_id']),None)
    if not binding['evidence_ids'] or source is None or source['source']!=binding['source_ref'] or source['physical_id']!=current['physical_id'] or binding['source_sha256']!=report['source_sha256'] or report.get('clock_id')!=current['target_clock_id']:
        return dict(status='unknown',reason='preview_source_clock_binding_unresolved',frames=[])
    known_source_sha=source['source'].get('sha256')
    if known_source_sha is not None and known_source_sha.lower()!=binding['source_sha256']:
        raise ValueError('preview source byte conflict')
    if not report.get('decoder_evidence_ids') or not report.get('physical_evidence_ids'):
        return dict(status='unknown',reason='preview_clock_evidence_missing',frames=[])
    for name in ('source_time_base','output_time_base','source_grid','output_grid'):
        values=report.get(name)
        if type(values) is not list or len(values)!=2: raise ValueError('preview grid/timebase missing')
        for value in values: integer(value,1)
    crop=report.get('crop')
    if type(crop) is not list or len(crop)!=4: raise ValueError('preview crop missing')
    for value in crop: integer(value,0)
    x0,y0,x1,y1=crop
    if not (x0<x1<=report['source_grid'][0] and y0<y1<=report['source_grid'][1]) or report['output_grid']!=[x1-x0,y1-y0]: raise ValueError('preview grid/crop conflict')
    rows=report.get('frames');segments=report.get('segments')
    if type(rows) is not list or not 0<len(rows)<=600 or type(segments) is not list: raise ValueError('bounded preview mapping required')
    indexed={};previous_segment_end=None
    for seg in segments:
        fields(seg,{'segment_id','clock_id','start_ns','end_ns'})
        text(seg['segment_id']);integer(seg['start_ns']);integer(seg['end_ns'])
        if (seg['segment_id'] in indexed or seg['clock_id']!=current['target_clock_id']
                or seg['end_ns']<=seg['start_ns']
                or (previous_segment_end is not None and seg['start_ns']<previous_segment_end)):
            raise ValueError('preview selection conflict')
        indexed[seg['segment_id']]=seg
        previous_segment_end=seg['end_ns']
    frames=[];previous=None
    for i,row in enumerate(rows):
        fields(row,{'decoder_index','pts','source_frame_idx','physical_ns','segment_id','output_frame_idx','output_pts'})
        for key in ('decoder_index','source_frame_idx','output_frame_idx'): integer(row[key],0)
        for key in ('pts','physical_ns','output_pts'): integer(row[key])
        seg=indexed.get(row['segment_id'])
        if row['output_frame_idx']!=i or seg is None or not seg['start_ns']<=row['physical_ns']<seg['end_ns']: raise ValueError('preview frame coverage conflict')
        if previous and any(row[k]<=previous[k] for k in ('decoder_index','pts','source_frame_idx','physical_ns','output_pts')): raise ValueError('preview frame order conflict')
        reconstructed=next(s for s in current['timeline_report']['segments'] if s['segment_id']==binding['segment_id'])
        if not covered([row['physical_ns'],row['physical_ns']+1],reconstructed.get('spans_ns',[])): raise ValueError('preview frame outside source coverage')
        previous=row
        seconds=Fraction(row['output_pts']*report['output_time_base'][0],report['output_time_base'][1])
        if not 0<=seconds<=86400: raise ValueError('preview presentation time outside bounds')
        frames.append(dict(output_frame_idx=i,source_frame_idx=str(row['source_frame_idx']),physical_ns=str(row['physical_ns']),segment_id=row['segment_id'],display_seconds=float(seconds)))
    cuts=[dict(after_output_frame_idx=i-1,before_output_frame_idx=i,continuity='cut') for i in range(1,len(rows)) if rows[i]['segment_id']!=rows[i-1]['segment_id']]
    if report.get('cuts')!=cuts: raise ValueError('preview cuts conflict')
    selection_coverage=union([span['interval_ns'] for span in current['spans']])
    if any(not covered([seg['start_ns'],seg['end_ns']],selection_coverage) for seg in segments):
        return dict(status='unknown',reason='preview_selection_revision_unresolved',frames=[])
    return dict(status='supplied_mapping',reason='physical_mapping_authenticity_unverified',asset=deepcopy(asset),frames=frames,cuts=cuts,
                source_sha256=report['source_sha256'],report_sha256=report['report_sha256'],source_grid=report['source_grid'],crop=crop,
                output_grid=report['output_grid'],segments=[dict(s,start_ns=str(s['start_ns']),end_ns=str(s['end_ns'])) for s in segments])


def validate_activity(document):
    validate_json(document)
    fields(document,{'schema','synthetic','candidates'})
    if document['schema']!='intake-activity-workbench/v1' or type(document['synthetic']) is not bool: raise ValueError('unsupported activity workbench')
    if type(document['candidates']) is not list or not 0<len(document['candidates'])<=100: raise ValueError('bounded candidates required')
    seen=set()
    for candidate in document['candidates']:
        fields(candidate,{'id','episode_id','label','history','artifacts','preview'}, {'gap_notes'})
        for key in ('id','episode_id','label'): text(candidate[key])
        if candidate['id'] in seen: raise ValueError('duplicate candidate')
        seen.add(candidate['id'])
        history=candidate['history']
        if type(history) is not list or not 0<len(history)<=100: raise ValueError('bounded complete history required')
        for index,selection in enumerate(history,1):
            evaluate_selection(selection)
            if selection['revision']!=index or selection['synthetic'] is not document['synthetic'] or selection['selection_id']!=history[0]['selection_id']: raise ValueError('history lineage conflict')
            if index>1 and selection['parent']['sha256']!=digest(history[index-2]): raise ValueError('history parent conflict')
        if type(candidate['artifacts']) is not list: raise ValueError('artifacts required')
        notes=candidate.get('gap_notes',[])
        if type(notes) is not list: raise ValueError('gap notes array required')
        spans=union([s['interval_ns'] for s in history[-1]['spans']])
        gaps=[[a[1],b[0]] for a,b in zip(spans,spans[1:])]
        noted=[]
        for note in notes:
            fields(note,{'interval_ns','reason','evidence_ids'})
            interval(note['interval_ns']);text(note['reason']);ids(note['evidence_ids'])
            if note['interval_ns'] not in gaps or note['interval_ns'] in noted: raise ValueError('gap note must bind one original gap')
            noted.append(note['interval_ns'])
        _preview(candidate,history[-1])
    return document


ACTIONS = {
    'preview_not_supplied': ('Preview missing', 'Supply a pinned source-linked preview, or retain a manual evidence-limited review.'),
    'preview_source_clock_binding_unresolved': ('Preview source or clock unresolved', 'Ask the source owner for an exact source, physical-clock and segment binding.'),
    'preview_clock_evidence_missing': ('Clock evidence missing', 'Supply decoder and physical-clock evidence before using mapped video times.'),
    'preview_selection_revision_unresolved': ('Preview is stale for this selection', 'Regenerate a pinned preview within the current selection boundaries before using mapped video times.'),
    'preview_invalidated_by_pending_proposal': ('Preview is historical for this proposal', 'Generate a new source-linked preview before treating mapped frames as proposal evidence.'),
    'physical_mapping_authenticity_unverified': ('Provenance unverified', 'Verify the supplied clock/source provenance outside this viewer; playback alone is insufficient.'),
    'activity_evidence_missing': ('Activity evidence missing', 'Attach the relevant inspection evidence to a reviewed source-bound selection.'),
    'activity_uncertainty_unresolved': ('Activity interpretation unresolved', 'Review the stated uncertainty with the activity owner; preserve uncertainty until resolved.'),
    'source_coverage_unresolved': ('Source coverage unresolved', 'Supply the missing chunk or timing coverage evidence.'),
    'span_outside_evidenced_coverage': ('Boundary outside known source coverage', 'Resolve source coverage or correct the boundary before export.'),
}


def actions_for(candidate, report, preview):
    reasons={r for span in report['spans'] for r in span['reasons']}
    reasons.add(preview['reason'])
    rows=[]
    for reason in sorted(reasons):
        title,action=ACTIONS.get(reason, ('Source evidence needs review', 'Ask the source owner to resolve this supplied evidence conflict before treating the selection as established.'))
        rows.append(dict(reason=reason,title=title,action=action,span_ids=[s['span_id'] for s in report['spans'] if reason in s['reasons']]))
    return rows


def _pending_for(candidate, document, pending):
    if pending is None:
        return None
    if type(pending) is not dict:
        raise ValueError('pending proposal must be an object')
    if pending.get('candidate_id') != candidate['id']:
        return None
    fields(pending, {'schema','candidate_id','snapshot_sha256','current_sha256','report_sha256','proposed','correction_receipt','invalidations','original_preview','preview_status','reviewer_authentication','status'})
    current=candidate['history'][-1];proposed=pending['proposed']
    if (pending['schema']!='intake-activity-pending-proposal/v1' or pending['status']!='pending_not_accepted'
            or pending['snapshot_sha256']!=digest(document) or pending['current_sha256']!=digest(current)
            or proposed['selection_id']!=current['selection_id'] or proposed['revision']!=current['revision']+1
            or proposed['parent']['sha256']!=digest(current) or pending['reviewer_authentication']!='not_verified'
            or pending['preview_status']!='original_only_not_regenerated_for_edit'):
        raise ValueError('pending proposal binding changed')
    correction=pending['correction_receipt']
    fields(correction,{'reviewer_id','evidence_ids','reason','previous_sha256','proposed_sha256'})
    if correction['previous_sha256']!=digest(current) or correction['proposed_sha256']!=digest(proposed):
        raise ValueError('pending correction receipt changed')
    return dict(status=pending['status'],revision=proposed['revision'],selection_sha256=digest(proposed),report_sha256=pending['report_sha256'],
                spans=[dict(s,interval_ns=list(map(str,s['interval_ns']))) for s in proposed['spans']],
                correction_receipt=deepcopy(correction),invalidations=deepcopy(pending['invalidations']),
                reviewer_authentication=pending['reviewer_authentication'],preview_status=pending['preview_status'])


def project_activity(document,pending=None):
    if document is None: return dict(schema='intake-activity-workbench-view/v1',status='unknown',candidates=[])
    validate_activity(document)
    rows=[]
    for candidate in document['candidates']:
        current=candidate['history'][-1];report=evaluate_selection(current)
        preview=_preview(candidate,current)
        imported=_pending_for(candidate,document,pending)
        if imported is not None and preview['status']=='supplied_mapping':
            preview=dict(preview,status='historical_mapping',reason='preview_invalidated_by_pending_proposal')
        source_coverage=union([span for source in current['timeline_report']['segments'] for span in source.get('spans_ns',[])])
        if source_coverage:
            time_origin=source_coverage[0][0];time_origin_label='Seconds from earliest supplied source-clock coverage boundary'
        else:
            time_origin=current['spans'][0]['interval_ns'][0];time_origin_label='Seconds from original selection start'
        spans=[dict(s,interval_ns=list(map(str,s['interval_ns']))) for s in current['spans']]
        rows.append(dict(id=candidate['id'],episode_id=candidate['episode_id'],label=candidate['label'],selection_id=current['selection_id'],
                         revision=current['revision'],current_sha256=digest(current),clock_id=current['target_clock_id'],
                         physical_id=current['physical_id'],recording_id=current['timeline_report']['recording_id'],
                         time_origin_ns=str(time_origin),time_origin_label=time_origin_label,
                         sources=[dict(segment_id=s['segment_id'],view_id=s['view_id'],physical_id=s['physical_id'],
                                       clock_id=s.get('target_clock_id'),status=s['status'],
                                       spans_ns=[[str(a),str(b)] for a,b in s.get('spans_ns',[])]) for s in current['timeline_report']['segments']],
                         history=[dict(revision=h['revision'],sha256=digest(h)) for h in candidate['history']],
                         gap_notes=[dict(n,interval_ns=list(map(str,n['interval_ns']))) for n in candidate.get('gap_notes',[])],
                         spans=spans,status=report['status'],preview=preview,actions=actions_for(candidate,report,preview),
                         reasons=sorted({r for s in report['spans'] for r in s['reasons']}),pending_proposal=imported))
    return dict(schema='intake-activity-workbench-view/v1',status='supplied',synthetic=document['synthetic'],snapshot_sha256=digest(document),candidates=rows)


def export_revision(document,request):
    validate_activity(document)
    fields(request,{'snapshot_sha256','candidate_id','current_sha256','bounds','reviewer_id','reason','evidence_ids'})
    if request['snapshot_sha256']!=digest(document): raise ValueError('stale snapshot')
    candidate=next((c for c in document['candidates'] if c['id']==request['candidate_id']),None)
    if candidate is None: raise ValueError('candidate missing')
    current=candidate['history'][-1]
    if request['current_sha256']!=digest(current): raise ValueError('stale revision')
    if evaluate_selection(current)['status']=='conflict': raise ValueError('source conflict requires new evidence')
    bounds=request['bounds']
    if type(bounds) is not list or len(bounds)!=len(current['spans']): raise ValueError('complete boundaries required')
    proposed=deepcopy(current)
    for original,row in zip(proposed['spans'],bounds):
        fields(row,{'span_id','start_ns','end_ns'})
        if row['span_id']!=original['span_id']: raise ValueError('span identity conflict')
        times=[]
        for key in ('start_ns','end_ns'):
            value=row[key]
            if type(value) is not str or re.fullmatch(r'-?(0|[1-9][0-9]{0,39})',value) is None: raise ValueError('exact decimal time string required')
            times.append(int(value))
        original['interval_ns']=times
    proposed['revision']+=1
    proposed['parent']=dict(revision=current['revision'],sha256=digest(current))
    if evaluate_selection(proposed)['status']=='conflict': raise ValueError('edited span conflicts with source evidence')
    native=dict(schema='intake-activity-revision/v1',history=deepcopy(candidate['history']),proposed=proposed,artifacts=deepcopy(candidate['artifacts']),
                correction=dict(reviewer_id=request['reviewer_id'],reason=request['reason'],evidence_ids=request['evidence_ids'],previous_sha256=digest(current),proposed_sha256=digest(proposed)))
    result=revise_selection(native)
    result['workbench_review_context']=dict(schema='intake-workbench-review-context/v1',snapshot_sha256=digest(document),
        original_preview=deepcopy(candidate['preview']),gap_notes=deepcopy(candidate.get('gap_notes',[])),
        preview_status='original_only_not_regenerated_for_edit',reviewer_authentication='not_verified')
    return result
