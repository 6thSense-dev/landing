"""Separate processing, clean review, and payment ledgers; register confirmed roster."""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    # Frozen DDL: future ORM changes must not change this migration.
    op.execute("""
CREATE TABLE ops_footage_reviews (
	run_id VARCHAR(120) NOT NULL, 
	recording VARCHAR(200) NOT NULL, 
	manifest_sha256 VARCHAR(64) NOT NULL, 
	decision VARCHAR(24) NOT NULL, 
	reviewer VARCHAR(320) NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	collection_date VARCHAR(10), 
	note TEXT NOT NULL, 
	PRIMARY KEY (run_id, recording), 
	FOREIGN KEY(run_id) REFERENCES ops_clean_runs (run_id)
)
    """)
    op.execute("""
CREATE TABLE ops_payouts (
	id VARCHAR(36) NOT NULL, 
	wearer_id BIGINT NOT NULL, 
	amount_krw INTEGER NOT NULL, 
	accepted_seconds FLOAT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	approved_by VARCHAR(320) NOT NULL, 
	approved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL, 
	recipient_id VARCHAR(80) NOT NULL, 
	source_currency VARCHAR(3) NOT NULL, 
	wise_profile_id VARCHAR(80) NOT NULL, 
	wise_environment VARCHAR(16) NOT NULL, 
	recipient_hash VARCHAR(128) NOT NULL, 
	quote_id VARCHAR(100), 
	transfer_id VARCHAR(100), 
	provider_status VARCHAR(80), 
	error TEXT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(wearer_id) REFERENCES ops_wearers (id), 
	UNIQUE (transfer_id)
)
    """)
    op.execute("""
CREATE TABLE ops_payout_items (
	run_id VARCHAR(120) NOT NULL, 
	recording VARCHAR(200) NOT NULL, 
	payout_id VARCHAR(36) NOT NULL, 
	manifest_sha256 VARCHAR(64) NOT NULL, 
	accepted_seconds FLOAT NOT NULL, 
	rate_krw_hour INTEGER NOT NULL, 
	collection_date VARCHAR(10) NOT NULL, 
	PRIMARY KEY (run_id, recording), 
	FOREIGN KEY(run_id) REFERENCES ops_clean_runs (run_id), 
	FOREIGN KEY(payout_id) REFERENCES ops_payouts (id)
)
    """)
    op.execute("""
CREATE INDEX ix_ops_payout_items_payout_id ON ops_payout_items (payout_id)
    """)
    op.execute("""
CREATE TABLE ops_payout_recipients (
	wearer_id BIGINT NOT NULL, 
	wise_recipient_id VARCHAR(80) NOT NULL, 
	recipient_hash VARCHAR(128) NOT NULL, 
	wise_profile_id VARCHAR(80) NOT NULL, 
	wise_environment VARCHAR(16) NOT NULL, 
	verified_name VARCHAR(200) NOT NULL, 
	updated_by VARCHAR(320) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (wearer_id), 
	FOREIGN KEY(wearer_id) REFERENCES ops_wearers (id)
)
    """)
    op.execute("""
CREATE TABLE ops_processing_jobs (
	recording VARCHAR(200) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	reason TEXT NOT NULL, 
	input_json TEXT NOT NULL, 
	attempts INTEGER NOT NULL, 
	lease_token VARCHAR(36), 
	lease_until TIMESTAMP WITH TIME ZONE, 
	result_run_id VARCHAR(120), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (recording)
)
    """)
    roster = [
        ("16A4A5", "한규태", "한그라픽스"),
        ("16A2B6", "최희웅", "최희웅"),
        ("4A636A", "윤정원", "아이픽스존"),
        ("1696C8", "김명천", "김명천"),
    ]
    db = op.get_bind()
    for camera, name, workplace in roster:
        existing = db.execute(
            sa.text("SELECT wearer_id FROM ops_cameras WHERE device_id=:camera"),
            {"camera": camera},
        ).scalar()
        if existing is not None:
            db.execute(
                sa.text(
                    "UPDATE ops_wearers SET rate_krw_hour=11000 WHERE id=:id AND rate_krw_hour IS NULL"
                ),
                {"id": existing},
            )
            db.execute(
                sa.text(
                    "UPDATE ops_episodes SET wearer_id=:wearer WHERE upper(replace(device_id, 'EGO-', ''))=:camera AND wearer_id IS NULL AND paid=false"
                ),
                {"camera": camera, "wearer": existing},
            )
            continue  # Never rewrite an existing camera assignment during a deployment.
        matches = (
            db.execute(
                sa.text(
                    "SELECT id FROM ops_wearers WHERE name=:name AND workplace=:workplace"
                ),
                {"name": name, "workplace": workplace},
            )
            .scalars()
            .all()
        )
        if len(matches) > 1:
            continue  # Ambiguous identities need an operator.
        wearer = (
            matches[0]
            if matches
            else db.execute(
                sa.text(
                    "INSERT INTO ops_wearers (name, workplace, location, note, rate_krw_hour) VALUES (:name, :workplace, 'South Korea', '배포 · camera roster confirmed 2026-09-14', 11000) RETURNING id"
                ),
                {"name": name, "workplace": workplace},
            ).scalar()
        )
        db.execute(
            sa.text(
                "UPDATE ops_wearers SET rate_krw_hour=11000 WHERE id=:id AND rate_krw_hour IS NULL"
            ),
            {"id": wearer},
        )
        db.execute(
            sa.text(
                "INSERT INTO ops_cameras (device_id, wearer_id) VALUES (:camera,:wearer) ON CONFLICT (device_id) DO UPDATE SET wearer_id=EXCLUDED.wearer_id WHERE ops_cameras.wearer_id IS NULL"
            ),
            {"camera": camera, "wearer": wearer},
        )
        db.execute(
            sa.text(
                "UPDATE ops_episodes SET wearer_id=:wearer WHERE upper(replace(device_id, 'EGO-', ''))=:camera AND wearer_id IS NULL AND paid=false"
            ),
            {"camera": camera, "wearer": wearer},
        )


def downgrade():
    # Contributor identities and their historical assignments are never rolled back.
    for table in (
        "ops_payout_items",
        "ops_payouts",
        "ops_payout_recipients",
        "ops_footage_reviews",
        "ops_processing_jobs",
    ):
        op.drop_table(table)
