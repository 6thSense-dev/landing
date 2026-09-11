"""Read-only reconstruction of explicitly evidenced source coverage, never usability.

Only integer-nanosecond continuous spans and explicit constant clock offsets are
supported. Frame counts, nominal FPS, filenames and wall times are not clocks.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path


def _json(value):
    active, pending = set(), [(value, 0, False)]
    while pending:
        item, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        if depth > 128:
            raise ValueError("JSON nesting exceeds maximum depth 128")
        if item is None or type(item) in (str, bool, int):
            continue
        if type(item) is float and math.isfinite(item):
            continue
        if type(item) not in (dict, list) or id(item) in active:
            raise ValueError("input must be finite, acyclic JSON")
        if isinstance(item, dict) and any(type(k) is not str for k in item):
            raise ValueError("JSON keys must be strings")
        active.add(id(item))
        pending.append((item, depth, True))
        pending.extend((child, depth + 1, False) for child in
                       (item.values() if isinstance(item, dict) else item))


def _text(value, name):
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonempty unpadded string")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} contains a control character")
    return value


def _integer(value, name):
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer (nanoseconds, never float)")
    return value


def _evidence(value):
    if type(value) is not list:
        raise ValueError("evidence_ids must be a list")
    return [_text(x, "evidence id") for x in value]


def _reference(ref):
    if ref is None:
        return []
    if type(ref) is not dict:
        raise ValueError("source must be an object or null")
    bucket = _text(ref.get("bucket"), "bucket")
    key = _text(ref.get("key"), "key")
    if any(c in key for c in "%\\:?#") or any(
        p in ("", ".", "..") or p != p.strip() for p in key.split("/")
    ):
        raise ValueError("source key must be canonical, not a URI or encoded alias")
    pins = []
    for kind in ("version_id", "etag", "sha256"):
        value = ref.get(kind)
        if value is None:
            continue
        _text(value, kind)
        if kind == "sha256":
            if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise ValueError("sha256 must be 64 hexadecimal characters")
            pins.append(("sha256", value.lower()))
        elif kind == "version_id" and value == "null":
            continue  # S3's null version alone is not an immutable identifier.
        else:
            pins.append((kind, bucket, key, value))
    return pins


def _union(spans):
    result = []
    for start, end in sorted(spans):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def reconstruct_timeline(document):
    """Return supplied-coverage reconstruction with evidence and uncertainty intact."""
    _json(document)
    if type(document) is not dict or document.get("schema") != "intake-timeline/v1":
        raise ValueError("expected intake-timeline/v1")
    _text(document.get("recording_id"), "recording_id")
    if type(document.get("synthetic")) is not bool:
        raise ValueError("synthetic must be explicitly true or false")
    segments = document.get("segments")
    if type(segments) is not list:
        raise ValueError("segments must be a list")
    rows, groups, identities = [], defaultdict(list), defaultdict(list)
    ids = set()
    for segment in segments:
        if type(segment) is not dict:
            raise ValueError("segment must be an object")
        sid = _text(segment.get("segment_id"), "segment_id")
        if sid in ids:
            raise ValueError("duplicate segment_id")
        ids.add(sid)
        physical = segment.get("physical_id")
        if physical is not None:
            _text(physical, "physical_id")
        _text(segment.get("view_id"), "view_id")
        lineage = _evidence(segment.get("lineage_evidence_ids", []))
        pins = _reference(segment.get("source"))
        order = segment.get("declared_order")
        if order is not None:
            _integer(order, "declared_order")
        discontinuity = segment.get("discontinuity_before")
        if discontinuity is not None and type(discontinuity) is not bool:
            raise ValueError("discontinuity_before must be boolean or null")
        reasons, mapped, clock, signature = [], [], None, None
        if physical is None or not lineage:
            reasons.append("physical_lineage_unknown")
        if not pins:
            reasons.append("source_binding_unknown")
        timing, mapping = segment.get("timing"), segment.get("mapping")
        if timing is None or mapping is None:
            reasons.append("timing_or_clock_mapping_missing")
        else:
            if type(timing) is not dict or type(mapping) is not dict:
                raise ValueError("timing and mapping must be objects")
            source_clock = _text(timing.get("clock_id"), "timing.clock_id")
            clock = _text(mapping.get("target_clock_id"), "target_clock_id")
            mapped_from = _text(mapping.get("source_clock_id"), "source_clock_id")
            if mapped_from != source_clock:
                reasons.append("source_clock_conflict")
            if timing.get("coverage_kind") != "continuous_intervals":
                reasons.append("continuous_coverage_not_established")
            if mapping.get("kind") != "constant_offset":
                reasons.append("unsupported_clock_mapping")
            offset = _integer(mapping.get("offset_ns"), "offset_ns")
            if not _evidence(timing.get("evidence_ids", [])):
                reasons.append("timing_evidence_missing")
            if not _evidence(mapping.get("evidence_ids", [])):
                reasons.append("mapping_evidence_missing")
            spans = timing.get("spans_ns")
            if type(spans) is not list:
                raise ValueError("spans_ns must be a list")
            if not spans:
                reasons.append("coverage_missing")
            for span in spans:
                if type(span) is not list or len(span) != 2:
                    raise ValueError("span must be [start_ns, end_ns]")
                start, end = (_integer(x, "span bound") for x in span)
                if end <= start:
                    raise ValueError("span must have positive half-open extent")
                mapped.append([start + offset, end + offset])
            signature = (physical, source_clock, clock, mapping.get("kind"), offset)
        row = {"segment_id": sid, "physical_id": physical,
               "view_id": segment["view_id"], "declared_order": order,
               "discontinuity_before": discontinuity, "target_clock_id": clock,
               "status": "unknown" if reasons else "reconstructed_from_supplied_evidence",
               "reasons": reasons, "spans_ns": [] if reasons else _union(mapped)}
        rows.append(row)
        if physical is not None:
            groups[physical].append(row)
        for pin in pins:
            identities[pin].append((row, signature, segment.get("source")))

    # Conflicting aliases invalidate the entire physical group, including other eyes.
    conflicts = set()
    for pin, aliases in identities.items():
        lineages = {row["physical_id"] for row, _, _ in aliases if row["physical_id"] is not None}
        signatures = {sig for _, sig, _ in aliases if sig is not None}
        hashes = {ref["sha256"].lower() for _, _, ref in aliases if ref.get("sha256")}
        etags = {ref["etag"] for _, _, ref in aliases if ref.get("etag")}
        if (len(lineages) > 1 or len(signatures) > 1 or len(hashes) > 1
                or (pin[0] == "version_id" and len(etags) > 1)):
            conflicts.update(lineages)
    for physical, members in groups.items():
        clocks = {row["target_clock_id"] for row in members if row["target_clock_id"] is not None}
        if len(clocks) > 1 or any("source_clock_conflict" in r["reasons"] for r in members):
            conflicts.add(physical)
    summaries = []
    for physical, members in sorted(groups.items()):
        if physical in conflicts:
            for row in members:
                row["status"] = "conflict"
                row["reasons"].append("physical_group_conflict")
                row["spans_ns"] = []
        spans = _union([span for row in members for span in row["spans_ns"]])
        known = sum(end - start for start, end in spans)
        complete = all(r["status"] == "reconstructed_from_supplied_evidence" for r in members)
        summaries.append({"physical_id": physical,
                          "status": "conflict" if physical in conflicts else "reconstructed" if complete else "unknown",
                          "target_clock_id": members[0]["target_clock_id"] if complete else None,
                          "spans_ns": spans, "known_subset_duration_ns": known,
                          "supplied_segments_duration_ns": known if complete else None,
                          "uncovered_between_known_spans_ns": [[a[1], b[0]] for a, b in zip(spans, spans[1:])],
                          "gap_interpretation": "supplied coverage only; unknown segments may cover gaps"})
    complete = bool(rows) and all(r["status"] == "reconstructed_from_supplied_evidence" for r in rows)
    return {"schema": "intake-timeline-report/v1", "synthetic": document["synthetic"],
            "recording_id": document["recording_id"], "source_input": copy.deepcopy(document),
            "segments": rows, "physical_recordings": summaries,
            "status": "conflict" if conflicts else "reconstructed" if complete else "unknown",
            "known_subset_duration_ns": sum(g["known_subset_duration_ns"] for g in summaries),
            "supplied_segments_duration_ns": sum(g["known_subset_duration_ns"] for g in summaries) if complete else None,
            "usable_duration_ns": None,
            "unknowns": ["activity_usability_not_evaluated", "collector_credit_not_evaluated",
                         "evidence_authenticity_not_verified", "media_not_decoded",
                         "recording_inventory_completeness_not_verified"],
            "media_actions": []}


def from_normalized(normalized, *, synthetic):
    """Import A01 declarations without turning FPS, order or filenames into time."""
    _json(normalized)
    if (type(normalized) is not dict or normalized.get("schema") != "intake-source-normalized"
            or normalized.get("schema_version") != "1"):
        raise ValueError("expected intake-source-normalized version 1")
    source = normalized.get("source")
    if type(source) is not dict or type(source.get("inventory")) is not list:
        raise ValueError("normalized source inventory is required")
    for item in source["inventory"]:
        if type(item) is not dict:
            raise ValueError("inventory entry must be an object")
        _text(item.get("path"), "inventory path")
        _reference(item.get("reference"))
    entries = {item["path"]: item for item in source["inventory"]}
    if len(entries) != len(source["inventory"]):
        raise ValueError("duplicate normalized inventory paths")
    declared = normalized.get("segments", [])
    if type(declared) is not list:
        raise ValueError("normalized segments must be a list")
    paths = []
    for item in declared:
        if type(item) is not dict:
            raise ValueError("normalized segment must be an object")
        paths.append(_text(item.get("path"), "declared path"))
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate normalized segment paths")
    paths.extend(p for p in entries if p.lower().endswith(".mp4") and p not in paths)
    segments = [{"segment_id": f"declaration-{i}", "physical_id": None,
                 "lineage_evidence_ids": [], "view_id": "unknown",
                 "source": entries.get(path, {}).get("reference"), "declared_order": i,
                 "timing": None, "mapping": None, "declared_path": path}
                for i, path in enumerate(paths)]
    return {"schema": "intake-timeline/v1", "recording_id": normalized.get("recording_id"),
            "synthetic": synthetic, "segments": segments,
            "normalized_declarations": copy.deepcopy(normalized)}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="local JSON file or - for stdin")
    parser.add_argument("--normalized", choices=("synthetic", "unverified-source"),
                        help="import format-adapter output with explicit provenance label")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text()
        document = json.loads(raw, object_pairs_hook=_unique)
        if args.normalized:
            document = from_normalized(document, synthetic=args.normalized == "synthetic")
        result = reconstruct_timeline(document)
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0 if result["status"] == "reconstructed" else 1
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
        print(f"invalid timeline input: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
