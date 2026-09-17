"""Untrusted browser manifests and narrowly scoped upload requests."""
import base64
import hashlib
import json
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.core.ops_scan import REC_RE

PART_BYTES = 16 * 1024 ** 2
MAX_FILE_BYTES = 100 * 1024 ** 3
MAX_BATCH_BYTES = 500 * 1024 ** 3
MAX_FILES = 2000
RECEIPT_NAME = '_upload_complete.json'
MEDIA = ('.mp4', '.mov', '.m4v', '.webm', '.egoc')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class FileIn(Input):
    path: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0, le=MAX_FILE_BYTES)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    modified_ms: int = Field(ge=0, le=100_000_000_000_000)

    @field_validator('path')
    @classmethod
    def path_ok(cls, value):
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}', p)
               for p in value.split('/')) or len(value.split('/')) > 5:
            raise ValueError('Use original camera filenames; hidden paths and traversal are not allowed.')
        return value


class BatchIn(Input):
    recording: str = Field(min_length=1, max_length=200)
    files: list[FileIn] = Field(min_length=2, max_length=MAX_FILES)

    @field_validator('recording')
    @classmethod
    def recording_ok(cls, value):
        if not REC_RE.fullmatch(value):
            raise ValueError('Choose a complete ego_YYYYMMDD_HHMMSS_CAMERA episode folder.')
        return value

    @model_validator(mode='after')
    def complete_folder(self):
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError('Duplicate filenames in this episode.')
        if 'metadata.json' not in paths or not any(p.lower().endswith(MEDIA) for p in paths):
            raise ValueError('Each episode needs metadata.json and its original recording files.')
        if next(f.size for f in self.files if f.path == 'metadata.json') > 1024 ** 2:
            raise ValueError('metadata.json is too large.')
        if sum(f.size for f in self.files) > MAX_BATCH_BYTES:
            raise ValueError('Episode exceeds 500 GiB.')
        return self

    def digest(self):
        payload = sorted([f.model_dump() for f in self.files], key=lambda f: f['path'])
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class PartIn(Input):
    number: int = Field(ge=1, le=10000)
    checksum: str = Field(min_length=44, max_length=44)

    @field_validator('checksum')
    @classmethod
    def sha256(cls, v):
        try:
            raw = base64.b64decode(v, validate=True)
        except ValueError as exc:
            raise ValueError('Invalid SHA-256 checksum.') from exc
        if len(raw) != 32:
            raise ValueError('Invalid SHA-256 checksum.')
        return v


class ReceivedPart(Input):
    number: int = Field(ge=1, le=10000)
    etag: str = Field(pattern=r'^"?[a-fA-F0-9]{32}"?$')


class PartsIn(Input):
    parts: list[PartIn] = Field(default_factory=list, max_length=6)
    received: list[ReceivedPart] = Field(default_factory=list, max_length=6)


class CompleteIn(Input):
    received: list[ReceivedPart] = Field(default_factory=list, max_length=6)
