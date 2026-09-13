"""Read and append task reviews. Reviewer and source pins are server-derived."""
import json
import hashlib
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.ops import require_ops
from app.core.db import get_session
from app.core.ops_activity_review import source_recordings, summarize, projection
from app.models import CleanRun, User
from app.models.ops_activity_review import ActivityReview, ActivityCriteria

router = APIRouter(prefix='/api/ops/clean/runs', tags=['ops'])
TaskID = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9_-]{1,80}$')]
Ns = Annotated[str, StringConstraints(strict=True, pattern=r'^(0|[1-9][0-9]{0,23})$')]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]

class Interval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recording: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)]
    start_ns: Ns
    end_ns: Ns
    judgment: Literal['accepted', 'excluded', 'unknown']
    reason: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)]

class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: TaskID
    expected_revision: int = Field(strict=True, ge=0, le=2147483646)
    manifest_sha256: Annotated[str, StringConstraints(strict=True, pattern=r'^[a-f0-9]{64}$')]
    criteria_version: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=80)]
    criteria_text: Text
    intervals: list[Interval] = Field(max_length=1000)

async def latest(db, run_id, task_id):
    return (await db.execute(select(ActivityReview).where(ActivityReview.run_id == run_id,
        ActivityReview.task_id == task_id).order_by(ActivityReview.revision.desc()).limit(1))).scalar_one_or_none()

async def source(db, run_id, lock=False, parse=True):
    statement = select(CleanRun).where(CleanRun.run_id == run_id)
    if lock: statement = statement.with_for_update()
    run = (await db.execute(statement)).scalar_one_or_none()
    if run is None: raise HTTPException(404, 'Unknown clean run.')
    if not parse: return run, []
    try: recordings = source_recordings(run)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise HTTPException(409, 'Pinned source timeline is unavailable; review cannot be evaluated.')
    return run, recordings

@router.get('/{run_id}/activity-review')
async def get_review(run_id: str, task_id: Annotated[TaskID, Query()], response: Response,
                     revision: Annotated[int | None, Query(ge=1, le=2147483647)] = None,
                     _: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    response.headers['Cache-Control'] = 'no-store'
    run, recordings = await source(db, run_id, parse=revision is None)
    review = await latest(db, run_id, task_id)
    latest_revision = review.revision if review else 0
    if revision is not None:
        review = (await db.execute(select(ActivityReview).where(ActivityReview.run_id == run_id,
            ActivityReview.task_id == task_id, ActivityReview.revision == revision))).scalar_one_or_none()
        if review is None: raise HTTPException(404, 'Unknown review revision.')
    elif review and review.manifest_sha256 != run.manifest_sha256:
        raise HTTPException(409, 'Saved review refers to another manifest. Inspect history before proceeding.')
    result = projection(run, task_id, recordings, review)
    result['latest_revision'] = latest_revision
    return result

@router.post('/{run_id}/activity-review')
async def save_review(run_id: str, request: Request, response: Response,
                      reviewer: User = Depends(require_ops), db: AsyncSession = Depends(get_session)):
    response.headers['Cache-Control'] = 'no-store'
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 262144:
            raise HTTPException(413, 'Review exceeds 256 KiB.')
        raw.extend(chunk)
    try: body = ReviewInput.model_validate_json(bytes(raw))
    except ValidationError:
        raise HTTPException(422, 'Invalid review fields. Use bounded text and decimal integer nanosecond strings.')
    run, recordings = await source(db, run_id, lock=True)
    previous = await latest(db, run_id, body.task_id)
    if previous and previous.manifest_sha256 != run.manifest_sha256:
        raise HTTPException(409, 'Existing review is pinned to another manifest; explicit supersession is required.')
    if body.manifest_sha256 != run.manifest_sha256 or body.expected_revision != (previous.revision if previous else 0):
        raise HTTPException(409, 'Review or manifest changed. Reload before saving a new revision.')
    intervals = [row.model_dump() for row in body.intervals]
    try: summarize(recordings, intervals)
    except ValueError as exc: raise HTTPException(422, str(exc))
    criteria_hash = hashlib.sha256(body.criteria_text.encode()).hexdigest()
    # Unique key serializes competing criteria versions even across runs.
    await db.execute(insert(ActivityCriteria).values(task_id=body.task_id, version=body.criteria_version,
        text=body.criteria_text, sha256=criteria_hash).on_conflict_do_nothing())
    criteria = await db.get(ActivityCriteria, (body.task_id, body.criteria_version))
    if criteria.sha256 != criteria_hash:
        raise HTTPException(409, 'This task criteria version already identifies different text. Use a new version.')
    review = ActivityReview(run_id=run_id, task_id=body.task_id, revision=body.expected_revision+1,
        manifest_sha256=run.manifest_sha256, criteria_version=body.criteria_version,
        criteria_text=body.criteria_text, intervals_json=json.dumps(intervals), sources_json=json.dumps(recordings), criteria_sha256=criteria_hash,
        reviewer_id=reviewer.id, reviewer_email=reviewer.email)
    db.add(review)
    await db.flush()
    result = projection(run, body.task_id, recordings, review)
    result['latest_revision'] = review.revision
    await db.commit()
    return result
