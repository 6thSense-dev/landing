import pytest
from sqlalchemy import select

from app.models import Lead


def test_lead_table_columns():
    cols = {c.name: c for c in Lead.__table__.columns}
    assert set(cols) == {
        "id",
        "name",
        "email",
        "organization",
        "kind",
        "product",
        "message",
        "created_at",
        "updated_at",
    }
    # Uniqueness is now the composite (email, kind) index, not a column-level
    # unique on email.
    assert cols["email"].unique is not True
    assert cols["name"].nullable is False
    assert cols["organization"].nullable is False
    assert cols["kind"].nullable is False
    assert cols["product"].nullable is True
    assert cols["message"].nullable is True


def test_lead_email_index():
    indexes = {ix.name for ix in Lead.__table__.indexes}
    assert any("created_at" in ix for ix in indexes)


def test_lead_email_kind_unique_index():
    idx = {ix.name: ix for ix in Lead.__table__.indexes}
    assert "leads_email_kind_key" in idx
    composite = idx["leads_email_kind_key"]
    assert composite.unique is True
    assert [c.name for c in composite.columns] == ["email", "kind"]


@pytest.mark.asyncio
async def test_insert_and_read_lead(db_session):
    db_session.add(
        Lead(name="A", email="a@x.com", organization="Acme", kind="waitlist")
    )
    await db_session.commit()
    rows = (await db_session.execute(select(Lead))).scalars().all()
    assert len(rows) == 1
    assert rows[0].email == "a@x.com"
