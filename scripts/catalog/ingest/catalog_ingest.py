"""catalog-ingest: turn a directory of raw takes into a buyer-facing catalog bundle.

    python3 -m ingest.catalog_ingest build --takes takes/ --out catalog/ --posters
    python3 -m ingest.catalog_ingest validate --out catalog/
    python3 -m ingest.catalog_ingest stats --out catalog/

WHY idempotence by content hash: a bundle that changes bytes on a no-op rebuild cannot be
diffed, mirrored or cached. Every output goes through `_write_if_changed`, so a run where
nothing moved rewrites nothing -- `catalog.json` included, its `generated_utc` carried
over rather than stamped afresh.
WHY one failed take does not abort the run: a drop is fifty takes and one always has a
missing sidecar; aborting makes the operator fix one problem per round trip. Failures are
caught, named in the report with path and reason, and the process exits 1.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import hashlib
import json
import os
import shutil
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark import (SPLITS, BenchmarkConfigError, build_manifest, build_splits, humanise,
                        measured_scope,
                        primary_series, series_id, validate_benchmark_config)
from .imu import ImuError, build_imu_preview
from .probe import (LayoutError, ProbeError, TakeLayout, digest_files, extract_poster,
                    extract_preview, frame_times, missing_tools, place_file, primary_video,
                    probe_video, resolve_layout, sha256_file, verify_checksums)
from .records import (ClipInputs, build_clip, build_package_contents, build_segments,
                      clip_id_from, expand_template, read_structured, slugify, summary_from_clip)
from .tactile import (DEFAULT_ADC_BITS, DEFAULT_CEILING_COUNTS, DEFAULT_DISPLAY_FULL_SCALE,
                      TactileError, TactileResult, build_tactile_preview)
from .validate import (normalization_from, probe_disagreements, render_report, render_table,
                       validate_bundle)

# Bumped whenever the ingest changes what it EMITS, not just how. It is published in
# `provenance.pipeline_version`, so a buyer can scope a defect to the clips it touched --
# and it is part of the per-take content hash, so a behaviour change invalidates the cache
# instead of quietly re-publishing records the old code produced.
PIPELINE_VERSION = "6s-catalog-ingest/1.1.0"
PATHS = {"detail": "clips/{id}.json", "poster": "posters/{id}.jpg", "preview": "previews/{id}.mp4"}
STATE_FILE, MODES = ".ingest-state.json", ("copy", "link", "reference")
_COLLECTION_NAMES = ("collection.toml", "collection.json", "collection.yaml", "collection.yml")


@dataclass
class BuildCtx:
    """Immutable per-run settings, shared by every worker thread."""
    out: Path
    media_mode: str
    posters: bool
    previews: bool
    force: bool
    strict: bool
    collection: dict
    collection_hash: str


@dataclass
class Plan:
    """A take resolved far enough to know its identity, before any heavy work."""
    layout: TakeLayout
    cfg: dict
    metadata: dict | None
    clip_id: str
    slug: str


@dataclass
class TakeResult:
    """Outcome of one take. `ok=False` means it is absent from the catalog, with a reason."""
    take_dir: Path
    clip_id: str
    ok: bool = True
    changed: bool = True
    error: str | None = None
    # A take the QA rule REFUSED is not a broken ingest. It is the rule working, so it is
    # reported under its own heading and does not set the exit code -- conflating the two
    # is how an operator learns to ignore a non-zero exit.
    quarantined: str | None = None
    summary: dict | None = None
    detail: dict | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    input_hash: str = ""


def _dumps(doc: Any) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _write_if_changed(path: Path, text: str) -> bool:
    """Write only when the bytes differ. Returns True when the file was touched."""
    data = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def _load_state(out: Path) -> dict:
    """Previous run's digest cache and summaries; empty when absent or unreadable."""
    try:
        return json.loads((out / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _input_hash(digests: dict[Path, str], ctx: BuildCtx) -> str:
    """One hash over every input byte plus the options that change the output."""
    body = "".join(f"{p.name}\0{digests[p]}\0" for p in sorted(digests))
    return hashlib.sha256(f"{body}{PIPELINE_VERSION}|{ctx.media_mode}|{ctx.posters}|"
                          f"{ctx.previews}|{ctx.collection_hash}".encode()).hexdigest()


def _tactile(plan: Plan, ctx: BuildCtx, t0_us: float | None, geo: dict) -> TactileResult:
    """Run the tactile builder with this take's own ceiling/scale, not global defaults."""
    meta = plan.metadata or {}
    tm, quality = (meta.get("modalities") or {}).get("tactile") or {}, meta.get("quality") or {}
    stills = ctx.out / "stills" / plan.clip_id
    for src in (s for s in plan.layout.stills if not (stills / s.name).exists()):
        stills.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, stills / src.name)
    return build_tactile_preview(
        plan.layout.tactile, grid=geo.get("grid"), clip_t0_us=t0_us,
        # H9 again: the converter's bit depth is a property of the hardware that
        # produced the counts, so it comes off the take. Publishing the ingest's
        # 16-bit default over a 12-bit rig quietly misstates the dynamic range.
        adc_bits=tm.get("adc_bits") or DEFAULT_ADC_BITS,
        peak_sidecar_path=ctx.out / "tactile" / f"{plan.clip_id}.peak.f32",
        peak_sidecar_url=f"tactile/{plan.clip_id}.peak.f32", index_rule=geo.get("index_rule"),
        ceiling_counts=float(tm.get("physical_ceiling_counts") or DEFAULT_CEILING_COUNTS),
        display_full_scale=float(tm.get("display_full_scale_counts") or DEFAULT_DISPLAY_FULL_SCALE),
        derive_delta=tm.get("derive_delta"), note=tm.get("full_scale_note"),
        # H9: raw ADC counts are only an honest unit when the bit depth, the observed
        # pedestal and the observed ceiling ship with them. The pedestal was measured by
        # the producer and was being dropped on the floor.
        pedestal_counts=tm.get("pedestal_counts"),
        still_paths=plan.layout.stills, still_url=lambda p: f"stills/{plan.clip_id}/{p.name}",
        # The census rules the PRODUCER applied, so `census.rules` describes the numbers
        # actually published rather than ours describing someone else's masks.
        meta_census={h: {"damage_note": (quality.get("damage_anatomy") or {}).get(h),
                         "silent_rule": quality.get("silent_channel_rule"),
                         "over_ceiling_rule": quality.get("rejection_rule"),
                         "intermittent_rule": quality.get("intermittent_channel_rule")}
                     for h in ("left", "right")})


def _archive(plan: Plan, ctx: BuildCtx) -> dict | None:
    """Assemble the whole take as one downloadable tar.gz, when the take asks for it.

    "Send me one clip end to end so I can run it through my loader" is the first thing a
    buyer asks for, and a catalog that answers it with a poster and two envelopes is a
    brochure. So a take marked `publish_archive` gets a real archive with a real digest
    that a buyer can verify before they open a single file.

    tar.gz rather than tar.zst: zstd needs a dependency or Python 3.14, and the point is
    that the download works everywhere, not that it is 8% smaller.
    """
    if not plan.cfg.get("publish_archive"):
        return None
    dest = ctx.out / "archives" / f"{plan.clip_id}.tar.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if ctx.force or not dest.is_file():
        tmp = dest.with_suffix(dest.suffix + ".part")
        # Deterministic: sorted members, and mtime/uid/gid/uname stripped, so a rebuild
        # from unchanged inputs produces the same bytes and the same digest.
        def _reset(info: tarfile.TarInfo) -> tarfile.TarInfo:
            info.mtime, info.uid, info.gid = 0, 0, 0
            info.uname = info.gname = ""
            return info
        with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
            for path in sorted(plan.layout.files):
                rel = path.relative_to(plan.layout.take_dir).as_posix()
                tar.add(path, arcname=f"{plan.clip_id}/{rel}", filter=_reset)
        tmp.replace(dest)
    return {"url": f"archives/{plan.clip_id}.tar.gz", "format": "tar.gz",
            "bytes": dest.stat().st_size, "sha256": sha256_file(dest)}


def _thumbs(plan: Plan, ctx: BuildCtx, probe) -> tuple[str | None, str | None]:
    """Poster and hover loop, always bundle-owned so the grid works in reference mode."""
    out: list[str | None] = []
    for kind, ext, want, cut in (("poster", ".jpg", ctx.posters, extract_poster),
                                 ("preview", ".mp4", ctx.previews, extract_preview)):
        dest = ctx.out / f"{kind}s" / f"{plan.clip_id}{ext}"
        shipped = plan.layout.take_dir / "preview" / f"{kind}{ext}"
        if (ctx.force or not dest.is_file()) and shipped.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(shipped, dest)
        elif (ctx.force or not dest.is_file()) and want and probe is not None:
            cut(probe.path, dest, duration_s=probe.duration_s)
        out.append(expand_template(PATHS[kind], plan.clip_id, plan.slug) if dest.is_file() else None)
    return out[0], out[1]


def _ingest(plan: Plan, ctx: BuildCtx, blobs: dict[str, str], cached: dict) -> TakeResult:
    """Build one clip. Every failure mode returns a TakeResult, never raises."""
    res = TakeResult(plan.layout.take_dir, plan.clip_id)
    try:
        digests = digest_files(plan.layout, blobs)
        res.input_hash = _input_hash(digests, ctx)
        detail = ctx.out / expand_template(PATHS["detail"], plan.clip_id, plan.slug)
        if (not ctx.force and cached.get("input_hash") == res.input_hash
                and detail.is_file() and cached.get("summary")):
            res.changed, res.summary = False, cached["summary"]
            res.warnings, res.notes = cached.get("warnings", []), cached.get("notes", [])
            # The manifest's split normalisation is derived from the detail records, so a
            # cached take still has to hand one back. Reading it is cheaper than rebuilding.
            res.detail = json.loads(detail.read_text(encoding="utf-8"))
            return res

        res.warnings += _structural_warnings(plan.layout)
        meta = plan.metadata or {}
        probe = None
        if (feed := primary_video(plan.layout)) is not None:
            probe = probe_video(feed)
            res.notes += probe_disagreements(probe, meta)
        elif not plan.layout.tactile:
            raise LayoutError("no video and no tactile: there is nothing to catalogue here")

        ft = frame_times(plan.layout.frame_times)
        stamps, t0_us = ft.rows, ft.first_us
        rel = lambda p: p.relative_to(plan.layout.take_dir).as_posix()  # noqa: E731
        media_url = lambda p: None if p is None else f"media/{plan.clip_id}/{rel(p)}"  # noqa: E731
        for path in plan.layout.files:
            place_file(path, ctx.out / "media" / plan.clip_id / rel(path), ctx.media_mode)
        # Taxel geometry: the layout sidecar wins, metadata.json is the fallback.
        sl = read_structured(plan.layout.sensor_layout) if plan.layout.sensor_layout else {}
        geo = {"grid": sl.get("grid") or ((meta.get("modalities") or {}).get("tactile")
                                          or {}).get("grid"),
               "index_rule": sl.get("index_rule"), "taxel_pitch_mm": sl.get("taxel_pitch_mm")}
        tac = _tactile(plan, ctx, t0_us, geo)
        res.warnings += tac.warnings

        imu_prev, imu_url, imu_status = None, None, "unverified"
        if plan.layout.imu_csv is not None:
            u = plan.cfg.get("imu_units") or {}
            got = build_imu_preview(
                plan.layout.imu_csv, sidecar_path=ctx.out / "imu" / f"{plan.clip_id}.f32",
                sidecar_url=f"imu/{plan.clip_id}.f32", clip_t0_us=t0_us,
                accel_units=u.get("accel", "m/s^2"), gyro_units=u.get("gyro", "rad/s"),
                frame=plan.cfg.get("imu_frame"),
                allow_zero_stream=bool(plan.cfg.get("imu_allow_zero")))
            imu_prev, imu_status = got.preview, ("operational" if got.preview else "failed")
            # media.imu.f32 is a DELIVERED file, so it is non-null only when a sidecar was
            # actually written. Under the contract's fixed rule a stream of <= 2000 readings
            # is carried inline and no .f32 exists; pointing at one anyway emits a URL that
            # 404s and that the bundle validator correctly rejects.
            imu_url = ((imu_prev or {}).get("sidecar") or {}).get("url")
            res.warnings += got.warnings

        segments, warn = build_segments(plan.layout.segcap)
        res.warnings += warn
        package, total = build_package_contents(plan.layout, digests, media_url)
        poster, preview = _thumbs(plan, ctx, probe)
        split = plan.cfg.get("split")
        if split is not None and split not in SPLITS:
            res.warnings.append(f"split={split!r} is not one of {SPLITS}; shipping null")
            split = None
        clip, warn = build_clip(ClipInputs(
            layout=plan.layout, clip_id=plan.clip_id, slug=plan.slug, cfg=plan.cfg,
            collection=ctx.collection, metadata=plan.metadata, probe=probe, tactile=tac,
            imu_preview=imu_prev, imu_status=imu_status, imu_f32_url=imu_url, segments=segments,
            package=package, total_bytes=total, media_url=media_url, frame_timestamps=stamps,
            urls={"poster": poster, "preview": preview,
                  "detail": expand_template(PATHS["detail"], plan.clip_id, plan.slug)},
            checksums_verified=verify_checksums(plan.layout, digests),
            pipeline=PIPELINE_VERSION, geometry=geo, split=split,
            cfr_divergence_ms=ft.cfr_divergence_ms,
            grid_divergence_ms=ft.grid_divergence_ms,
            frames_missing_on_grid=ft.frames_missing_on_grid,
            license_file_url=media_url(plan.layout.docs.get("license"))))
        res.warnings += warn
        clip["media"]["archive"] = _archive(plan, ctx)

        if clip["qa"]["disposition"] != "accepted":
            failed = ", ".join(c["check_id"] for c in clip["qa"]["checks"]
                               if c["result"] == "fail")
            res.ok = False
            res.quarantined = (f"QA disposition {clip['qa']['disposition']!r}: {failed}. "
                               f"Only 'accepted' clips may appear in the catalog.")
            return res
        if ctx.strict and res.warnings:
            raise LayoutError(f"--strict: {len(res.warnings)} warning(s), 1st: {res.warnings[0]}")
        _write_if_changed(detail, _dumps(clip))
        res.summary = summary_from_clip(clip, PATHS)
        res.detail = clip
    except (LayoutError, ProbeError, ImuError, TactileError, OSError, ValueError, KeyError) as exc:
        res.ok, res.error = False, f"{type(exc).__name__}: {exc}"
    return res


def _structural_warnings(lay: TakeLayout) -> list[str]:
    """Name every absent input a buyer will notice: the WARN rows of INTAKE.md section 5.
    Each becomes an em-dash on a card or a `not_run` check, so the operator hears first."""
    return [note for cond, note in (
        (lay.config_path is None, "no take.toml: title, category, country and rights fall back "
         "to derived or fail-closed values"),
        (lay.metadata_path is None, "no metadata.json: sync, calibration, CRC rates and the "
         "channel census are all null, and the grade is capped at C"),
        (lay.frame_times is None and bool(lay.video), "no video/frame_times.csv: the H2 frame-"
         "count-equals-timestamp-count check records not_run, and the grade is capped at C"),
        (not (lay.calibration_raw or lay.calibration_delivered),
         "no calibration files: H7 is unmet and the clip is unsellable to anyone doing geometry"),
        (bool(lay.calibration_raw) and lay.calibration_delivered is None, "only the raw solve "
         "ships: applying it to the delivered panes costs tens of pixels of rectification error"),
        (bool(lay.tactile) and lay.sensor_layout is None,
         "no sensor_layout.json: a zero-reading taxel is indistinguishable from a missing one"),
    ) if cond]


def _plan(take_dir: Path, taken: set[str]) -> Plan:
    """Resolve identity serially so slugs are deterministic regardless of --jobs."""
    lay = resolve_layout(take_dir)
    cfg = read_structured(lay.config_path) if lay.config_path else {}
    cid = clip_id_from(lay.take_id)
    return Plan(lay, cfg, read_structured(lay.metadata_path) if lay.metadata_path else None,
                cid, slugify(cfg.get("title"), cid, taken))


def _open_sample(clips: list[dict], details: dict[str, dict]) -> dict | None:
    """The one clip a prospect may download without a contract.

    Two conditions, both non-negotiable: an archive was actually assembled, and all four
    per-clip permissions read `granted`. Advertising an open sample whose rights are
    anything less would be the same overstatement the rest of the contract exists to stop.
    """
    for clip in sorted(clips, key=lambda c: c["id"]):
        archive = ((details.get(clip["id"]) or {}).get("media") or {}).get("archive")
        if not archive or not archive.get("url"):
            continue
        if all(clip["rights"][k] == "granted" for k in
               ("model_training", "commercial_use", "redistribution", "derived_model")):
            return {"clip_id": clip["id"], "url": archive["url"], "format": archive["format"],
                    "bytes": archive["bytes"], "sha256": archive["sha256"]}
    return None


def _manifest(ctx: BuildCtx, clips: list[dict], plans: list[Plan],
              details: dict[str, dict]) -> dict:
    """Subjects and sessions are counted distinct, never summed: one operator across four
    takes is one subject. Either goes null unless EVERY take declares it -- a partial count
    presented as a total is the same lie as a partial byte sum."""
    by_id = {p.clip_id: p for p in plans}
    # Our own series id comes from [benchmark.series] in collection.toml, falling back
    # to the collection id -- renaming the dataset in the legend is a one-line edit.
    cid = primary_series(ctx.collection)[0]
    counted = lambda k: (len({p.cfg[k] for p in plans})  # noqa: E731
                         if plans and all(p.cfg.get(k) for p in plans) else None)
    # H10: the constants are fitted over the TRAIN clips and nothing else. Computing them
    # over the whole collection would leak test statistics into training, and the scope is
    # published so a buyer can check we did not -- validate_bundle recomputes it.
    train = [c for c in clips if c.get("split") == "train"]
    norm = None
    if train:
        norm = {"scope": "train",
                "statement": "Fitted on the train split only. Val and test clips contributed "
                             "nothing to these constants.",
                **normalization_from(train, details)}
    return build_manifest(
        ctx.collection, clips, paths=PATHS,
        generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        subjects=counted("operator"), sessions=counted("session_id"),
        splits=build_splits(ctx.collection, clips, norm),
        sample_archive=_open_sample(clips, details),
        # The collection-level sync aggregate (H1) and the recorded/synthetic
        # provenance class both fold over the DETAIL records, not the summaries.
        details=details,
        series_of=lambda c: (series_id(by_id[c["id"]].cfg["dataset"])
                             if by_id[c["id"]].cfg.get("dataset") else cid),
        task_of=lambda c: (by_id[c["id"]].cfg.get("task")
                           or humanise(c["subcategory"] or c["category"])),
        # The category roll-up keys on the MACHINE value, not on a label, so a chart bar
        # joins to facets.category[].value by equality and the filter bar and the chart
        # cannot disagree about what "Industrial inspection" selects.
        category_of=lambda c: c.get("category"))


def _restamp_scope(details: dict[str, dict]) -> list[str]:
    """Correct every record's `check.scope` against what the whole drop measured.

    Returns the clip ids whose bytes changed, so only those get rewritten.

    validate.py tags a check `collection` from a static candidate list, because it is
    handed one take at a time and cannot know how the others answered. That list is a
    statement of intent; this is the measurement. Keeping only the candidates that ACTUALLY
    miss their bound on every clip is what stops a varying check -- a privacy warning on 10
    clips of 30, say -- being filed under "applies to the whole collection, not to this
    clip" on the ten pages it is genuinely about.

    Demotion only. A check outside the candidate list is never promoted to `collection`
    however uniformly it answers, because uniform-by-accident is not the same as
    programme-scoped, and a corpus of two clips would otherwise promote almost everything.
    """
    keep = measured_scope(details)
    touched = []
    for cid, doc in details.items():
        changed = False
        for c in ((doc.get("qa") or {}).get("checks") or []):
            if c.get("scope") == "collection" and c.get("check_id") not in keep:
                c["scope"] = "clip"
                changed = True
        if changed:
            touched.append(cid)
    return touched


def cmd_build(args: argparse.Namespace) -> int:
    takes_dir, out = Path(args.takes).resolve(), Path(args.out).resolve()
    cfg_path = (Path(args.collection).resolve() if args.collection else
                next((takes_dir / n for n in _COLLECTION_NAMES if (takes_dir / n).is_file()), None))
    if cfg_path is None:
        print(f"error: no collection.toml/json/yaml in {takes_dir} and no --collection given",
              file=sys.stderr)
        return 2
    cfg = read_structured(cfg_path)
    # Judged before any take is read: an unsourced comparison series or a bad unit is a
    # one-second failure with a fix in the message, not a full ingest that dies at the
    # manifest after ten minutes of ffmpeg.
    try:
        validate_benchmark_config(cfg)
    except BenchmarkConfigError as exc:
        print(f"error: {cfg_path}: {exc}", file=sys.stderr)
        return 2
    chash = hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()
    ctx = BuildCtx(out, args.media_mode, args.posters, args.previews, args.force, args.strict,
                   cfg, chash)
    taken: set[str] = set()
    plans: list[Plan] = []
    failed: list[TakeResult] = []
    for d in sorted(p for p in takes_dir.iterdir() if p.is_dir() and p.name[0] != "."):
        try:
            plans.append(_plan(d, taken))
        except (LayoutError, OSError, ValueError) as exc:
            failed.append(TakeResult(d, d.name, ok=False, error=f"{type(exc).__name__}: {exc}"))
    if args.dry_run:
        for p in plans:
            print(f"  would build {p.clip_id}  <- {p.layout.take_dir}")
        print(f"{len(plans)} take(s) planned, {len(failed)} unreadable")
        return 1 if failed else 0
    out.mkdir(parents=True, exist_ok=True)
    state = _load_state(out)
    blobs: dict[str, str] = {} if state.get("collection_hash") != chash else state.get("blobs", {})
    jobs = max(1, args.jobs or (os.cpu_count() or 2) - 1)
    with futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(
            lambda p: _ingest(p, ctx, blobs, (state.get("takes") or {}).get(p.clip_id, {})), plans))
    results += failed
    clips = [r.summary for r in results if r.ok and r.summary]
    shipped = {c["id"] for c in clips}  # a skipped take must not drag the totals to null
    details = {r.clip_id: r.detail for r in results if r.ok and r.detail}
    # `scope` is the only field a clip record cannot determine on its own: whether a check
    # describes the programme or the take is a fact about the OTHER clips. validate.py
    # stamps a candidate from a static list because it sees one take at a time; here, with
    # every record in hand, the candidate is confirmed against what was actually measured.
    # A check that does not miss its bound on every clip goes back to being a clip fact,
    # which is what keeps this field and `collection_wide_limitations` describing the same
    # set. Rewritten AFTER the cache restore above, so a clip skipped as unchanged is
    # re-stamped too -- its scope depends on its neighbours, and a neighbour may have moved.
    _slug = {p.clip_id: p.slug for p in plans}
    for cid in _restamp_scope(details):
        _write_if_changed(ctx.out / expand_template(PATHS["detail"], cid, _slug[cid]),
                          _dumps(details[cid]))
    try:
        manifest = _manifest(ctx, clips, [p for p in plans if p.clip_id in shipped], details)
    except BenchmarkConfigError as exc:
        # Reached by the country-label rule: a clip carries a code the facet builder
        # cannot name, and a filter bucket reading `HK (12)` next to `China (18)` is
        # indistinguishable from a deliberate abbreviation. Fail with the fix in the
        # message rather than shipping the bare code.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    path = out / "catalog.json"
    if path.is_file():  # keep the old timestamp when nothing else moved, so bytes are stable
        old = json.loads(path.read_text(encoding="utf-8"))
        drop = lambda d: {k: v for k, v in d.items() if k != "generated_utc"}  # noqa: E731
        manifest = old if drop(old) == drop(manifest) else manifest
    touched = _write_if_changed(path, _dumps(manifest))
    (out / STATE_FILE).write_text(json.dumps(
        {"collection_hash": chash, "blobs": blobs, "media_mode": args.media_mode,
         "takes": {r.clip_id: {"input_hash": r.input_hash, "summary": r.summary,
                               "warnings": r.warnings, "notes": r.notes}
                   for r in results if r.ok}}), encoding="utf-8")

    rows = validate_bundle(out, Path(args.schema_dir), media_mode=args.media_mode)
    _write_if_changed(out / "INGEST_REPORT.md", render_report(
        manifest, [r.__dict__ for r in results], rows, media_mode=args.media_mode))
    held = [r for r in results if r.quarantined]
    bad = [r for r in results if not r.ok and not r.quarantined]
    for r in bad:
        print(f"  FAILED {r.take_dir}: {r.error}", file=sys.stderr)
    for r in held:
        print(f"  QUARANTINED {r.take_dir}: {r.quarantined}", file=sys.stderr)
    # A FAIL row means the bundle contradicts itself -- a schema violation, a facet count
    # that does not match clips[], a sidecar of the wrong length, a headline skew smaller
    # than a bound derivable from the same record. This validator is the guard rail under
    # every other claim in the contract, so it sets the exit code. It used not to, which
    # meant CI could ship an internally inconsistent bundle green.
    failed_rows = [r for r in rows if r.status == "FAIL"]
    for r in failed_rows:
        print(f"  BUNDLE FAIL {r.check}: {r.detail}", file=sys.stderr)
    changed = sum(1 for r in results if r.ok and r.changed) + (1 if touched else 0)
    print(f"{len(clips)} clip(s) in catalog, {changed} changed, {len(bad)} failed, "
          f"{len(held)} quarantined, {len(failed_rows)} bundle check(s) failed, "
          f"{sum(len(r.warnings) for r in results)} warning(s)  ->  {out}\n"
          f"  report: {out / 'INGEST_REPORT.md'}")
    return 1 if (bad or failed_rows) else 0


def cmd_validate(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    rows = validate_bundle(out, Path(args.schema_dir),
                           media_mode=_load_state(out).get("media_mode") or args.media_mode)
    print(render_table(rows))
    return 1 if any(r.status == "FAIL" for r in rows) else 0


def cmd_stats(args: argparse.Namespace) -> int:
    path = Path(args.out).resolve() / "catalog.json"
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    doc = json.loads(path.read_text(encoding="utf-8"))
    col, tot = doc["collection"], doc["collection"]["totals"]
    # Quote the runtime in the unit the header will render it in. Printing "0.3125 hours"
    # for a twenty-minute corpus here is the same defect as printing it on the page.
    unit = tot.get("duration_unit") or "hours"
    scale, suffix = (60.0, "min") if unit == "minutes" else (1.0, "h")
    bench = doc.get("benchmark") or {}
    bars = sorted((sum(t["values"].values()) for t in bench.get("tasks") or []), reverse=True)
    print(f"{col['name']}  v{col['version']}  ({col['id']})")
    rows = [("generated", doc["generated_utc"]), ("clips", tot["clips"]),
            ("runtime", f"{tot['hours'] * scale:,.2f} {suffix}   "
                        f"(stored as {tot['hours']:.6f} h; duration_unit={unit})"),
            ("usable tactile", f"{tot['tactile_usable_hours'] * scale:,.2f} {suffix} "
                               f"of {tot['tactile_hours'] * scale:,.2f} {suffix} wall clock"),
            ("bytes", tot["bytes"] or "—"),
            ("countries", ", ".join(tot["countries"]) or "—"),
            ("categories", ", ".join(tot["categories"]) or "—"),
            ("date range", " .. ".join(tot["date_range"] or []) or "—")]
    if bars:
        rows.append(("chart", f"unit={bench['unit']}  {len(bench['series'])} series  "
                              f"{len(bars)} bars  largest {bars[0]:,.4g}  "
                              f"smallest {bars[-1]:,.4g}"))
    if bench.get("note"):
        rows.append(("chart note", bench["note"]))
    rows += [(n, ", ".join(f"{b['label']} ({b['clips']})" for b in bk[:8]))
             for n, bk in (doc.get("facets") or {}).items()]
    print("\n".join(f"  {label:<15} {value}" for label, value in rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="catalog-ingest", description=__doc__.split("\n")[0])
    ap.add_argument("--schema-dir", default=str(Path(__file__).resolve().parent.parent / "schema"),
                    help="directory holding catalog.schema.json and clip.schema.json")
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build the catalog bundle from a takes directory")
    b.add_argument("--takes", required=True, help="directory whose subdirectories are takes")
    b.add_argument("--out", required=True, help="catalog root to write")
    b.add_argument("--media-mode", choices=MODES, default="copy",
                   help="how take media is materialised; the manifest is identical in all "
                        "three. copy (default) hard-links within a filesystem, so a bundle "
                        "is self-contained and servable for the cost of an inode per file; "
                        "reference leaves the bytes in the takes tree and emits a manifest "
                        "whose media URLs only resolve once something else places them")
    b.add_argument("--collection", help="path to collection.toml/json/yaml")
    b.add_argument("--jobs", type=int, default=0, help="parallel takes (default cpu_count-1)")
    for flag, note in (("posters", "extract a poster frame per clip"),
                       ("previews", "cut a 3 s silent hover loop per clip"),
                       ("force", "rebuild even when inputs are unchanged"),
                       ("dry-run", "list what would be built, write nothing"),
                       ("strict", "treat any warning as fatal for its take")):
        b.add_argument(f"--{flag}", action="store_true", help=note)
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("validate", help="re-validate an emitted bundle")
    v.add_argument("--out", required=True)
    v.add_argument("--media-mode", choices=MODES, default="copy")
    v.set_defaults(func=cmd_validate)
    s = sub.add_parser("stats", help="print collection totals and facets")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    if args.command == "build" and (gone := missing_tools()):
        print(f"warning: {', '.join(gone)} not on PATH; media cannot be measured", file=sys.stderr)
    try:  # anything else is a bug and should surface with its traceback
        return args.func(args)
    except (LayoutError, ProbeError, OSError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
