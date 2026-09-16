"""Collection geography from preserved source provenance, not a current profile."""
import re

REGIONS = {"korea": "Korea", "china": "China", "vietnam": "Vietnam", "india": "India"}
ALIASES = {**{key: key for key in REGIONS}, "kr": "korea", "cn": "china", "vn": "vietnam", "in": "india"}


def _labels(record):
    values = []
    for mapping in (record, record.get("tags", {})):
        if isinstance(mapping, dict):
            for field in ("region", "country"):
                value = mapping.get(field)
                if value:
                    values.append(ALIASES.get(str(value).strip().lower(), "unknown"))
    return set(values)


def clean_region(doc):
    """A mixed or incompletely attributed batch is held together for region review.

    Historical session names are retained in version-pinned source manifests even
    after Raw deletion. Never derive geography from names, camera owners or rates.
    No S3 reads or writes are needed for this display-only classification.
    """
    regions = _labels(doc)
    missing = False
    for recording in doc["recordings"]:
        inherited = _labels(doc) | _labels(recording)
        sources = recording.get("sources", [])
        if not sources:
            missing |= not inherited
        regions |= inherited
        for source in sources:
            found = inherited | _labels(source)
            parts = str(source.get("key", "")).split("/")
            if len(parts) > 2 and parts[0] == "sessions":
                session = parts[1].lower()
                found |= {key for key in REGIONS if re.search(rf"(?:^|[_-]){key}(?:$|[_-])", session)}
                if not found and re.search(r"(?:^|[_-])(?:trial|flowtest)(?:$|[_-])", session):
                    found.add("test")
            regions |= found
            missing |= not found
    if len(regions) == 1 and not missing and "unknown" not in regions:
        key = next(iter(regions))
        return {"key": key, "label": REGIONS.get(key, "Test footage"), "status": "classified"}
    return {"key": "unassigned", "label": "Needs region review", "status": "conflicting" if len(regions) > 1 else "missing"}
