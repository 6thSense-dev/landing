"""ORM models for the collector-operations area: wearers and episodes.

WHY THESE TABLES EXIST AT ALL
  The collector ledger began as a JSON file on one laptop
  (~/.egocam-ledger/ledger.json) whose own header says it "is the only copy of
  who was paid what". That is a payment record with no redundancy, no audit
  trail and no second reader. These tables are that file, in Postgres.

WHY A WEARER IS NOT A USER
  `users` is the login table. A wearer is a person who carried a camera; almost
  none of them will ever log in, and the ones who do must not become one row
  with two meanings. Deleting a login must not delete the payment history of
  the person it belonged to, which a shared table cannot promise.

WHY THE EPISODE CARRIES ITS OWN wearer_id
  The laptop ledger attributes an episode by looking up which collector held
  that device on that date. That is the right default and the wrong permanent
  record: a camera handed over at lunchtime splits a day no date range can
  express, and re-keying a range silently rewrites who was paid for episodes
  already settled. Resolve once, store the answer on the episode, and history
  stops moving.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.lead import Base


#: How an episode was removed. 'soft' hides it from the working view and keeps
#: every byte; 'hard' additionally deletes the objects from S3 and is for
#: captures that are worth less than their storage. Both keep the ROW: an
#: episode that was paid for and then purged is exactly the thing a payment
#: ledger must still be able to account for, and the raw bucket denies deletes
#: to its uploaders, so a purge is not something that can be undone by re-upload.
DELETE_KINDS: tuple[str, ...] = ("soft", "hard")

#: The task taxonomy already in use in the delivered takes catalog
#: (~/Desktop/6thSense_Takes_Catalog/vocabulary-takes_meta.json), which grades
#: every episode as category -> task. Reproduced here rather than invented,
#: because a label that does not match the one already shipped to a customer
#: splits the same activity into two names and makes the dataset unsearchable.
TASK_CATEGORIES: tuple[str, ...] = (
    "cleaning_and_waste",
    "electronics_assembly",
    "packing_and_folding",
    "pick_place_kitting",
    "soldering_and_bonding",
    "other",
)

#: Seeded by migration 0010, verbatim from that catalog.
SEED_TASKS: tuple[tuple[str, str], ...] = (
    ("cleaning_and_waste", "Floor Sweeping"),
    ("cleaning_and_waste", "Waste Bagging"),
    ("electronics_assembly", "Enclosure Assembly"),
    ("electronics_assembly", "Screw Assembly"),
    ("packing_and_folding", "Blanket Folding"),
    ("packing_and_folding", "Carton Folding"),
    ("packing_and_folding", "Garment Folding"),
    ("pick_place_kitting", "Dart Placement"),
    ("pick_place_kitting", "Module Inspection"),
    ("pick_place_kitting", "Print Removal"),
    ("pick_place_kitting", "Tray Kitting"),
    ("soldering_and_bonding", "Hot-Glue Bonding"),
    ("soldering_and_bonding", "PCB Soldering"),
)


class Wearer(Base):
    """A person who carries a camera. Not a login — see the module docstring."""

    __tablename__ = "ops_wearers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Free-form and optional on purpose. A collector is onboarded in a car park
    #: with a phone; requiring an email or a phone number here would mean either
    #: a blocked row or a fake one.
    contact: Mapped[str] = mapped_column(String(320), nullable=False, server_default="")
    workplace: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    location: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    rate_krw_hour: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ops_wearers_name_idx", "name"),)


class Task(Base):
    """What the wearer was doing. A controlled list, not free text on the episode.

    Free text would be quicker to build and would fragment the dataset inside a
    week -- "folding", "Folding", "fold laundry" and "Garment Folding" are one
    activity and four labels, and the whole value of the label is that takes of
    the same activity group. The list is editable, so an activity nobody
    anticipated is one row rather than a schema change.
    """

    __tablename__ = "ops_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    #: Matches the delivered catalog's `category` field. Free-form rather than a
    #: CHECK: the taxonomy is a working vocabulary, and a new category should not
    #: need a migration on a Friday.
    category: Mapped[str] = mapped_column(String(60), nullable=False, server_default="other")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ops_tasks_category_idx", "category"),)


class Episode(Base):
    """One recording in the capture bucket, plus what ops decided about it."""

    __tablename__ = "ops_episodes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: The recording folder name, e.g. ego_20260904_061840_4A62F8. Unique: it is
    #: the bucket's own identifier and a scan MERGES on it.
    recording: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    session: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    #: The camera that RECORDED it, read from the recording's metadata.json --
    #: not inferred from the S3 key. A card moved between bodies puts one
    #: camera's episode under another camera's prefix, which has already
    #: happened once; the metadata is the truth and the key is not.
    device_id: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    prefix: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: S3's LastModified for the take's LAST object -- when delivery FINISHED.
    #: An independent clock from the camera's, which is what makes the skew
    #: check possible and what "has this camera gone quiet" is measured against.
    #: Taking the first object instead would score a stalled multi-hour upload
    #: as if it had finished instantly.
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    files: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    frames: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dropped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: 'ntp' | 'client' | '' -- anything but 'ntp' means started_at may be hours
    #: wrong, which moves an episode into the wrong week or the wrong person's
    #: range. Carried through to the UI and flagged rather than quietly trusted.
    clock_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="")
    fw: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    no_metadata: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    wearer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ops_wearers.id", ondelete="SET NULL"))
    #: SET NULL, not CASCADE: retiring a task label must not delete the episodes
    #: that carried it. They become unlabelled and get relabelled, which is a
    #: chore; deleting them would be a loss.
    task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ops_tasks.id", ondelete="SET NULL"))
    #: Reviewed and accepted for payment. Distinct from the automatic quality
    #: verdict the scan computes: a human said yes.
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount_krw: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_kind: Mapped[str | None] = mapped_column(String(8))
    #: Who pressed delete and why. A purge that nobody can account for is worse
    #: than the bytes it saved.
    deleted_by: Mapped[str] = mapped_column(String(320), nullable=False, server_default="")
    delete_reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "delete_kind IS NULL OR delete_kind IN ('soft', 'hard')",
            name="ops_episodes_delete_kind_check",
        ),
        # A delete has both halves or neither. Half a delete renders as present
        # in one view and gone in another.
        CheckConstraint(
            "(deleted_at IS NULL) = (delete_kind IS NULL)",
            name="ops_episodes_delete_pair_check",
        ),
        Index("ops_episodes_session_idx", "session"),
        Index("ops_episodes_wearer_idx", "wearer_id"),
        Index("ops_episodes_task_idx", "task_id"),
        Index("ops_episodes_started_idx", "started_at"),
        Index("ops_episodes_uploaded_idx", "uploaded_at"),
    )


class OpsSetting(Base):
    """Board-wide settings for the operations area. Today that is one number.

    WHY A TABLE AND NOT THE OPERATOR'S BROWSER
      The payment rate is not a display preference -- every payment row is
      stamped with the rate that was in force when it was ticked. Two operators
      whose browsers held two different rates would write two different payment
      records for the same shift, and the ledger would have no way to say which
      was meant. It lives next to the episodes it prices.

    Keyed rather than a one-row table with a column per setting: the next
    setting should be an INSERT, not a migration.
    """

    __tablename__ = "ops_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
