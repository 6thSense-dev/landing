"""add the guest role

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-23

Adds 'guest' to users_role_check so the single shared, read-only demo account
can exist. Prospects are given one credential at /login and see the data
catalog and nothing else.

The role carries no database privilege of its own — every restriction is
enforced in the application layer (app/api/routes/*, app/core/auth_deps.py).
This migration only makes the row insertable, and mirrors the CheckConstraint
in app/models/user.py, which is what the test suite actually builds its schema
from.

WHY A CHECK CONSTRAINT AND NOT AN ENUM
  users.role has been a CHECK since 0002 and 0006 established the
  drop-and-recreate idiom for widening it. A Postgres ENUM would need
  ALTER TYPE ... ADD VALUE, which historically cannot run inside a transaction
  block and cannot be removed at all. Staying with the CHECK keeps upgrade and
  downgrade symmetric.

WHY THIS MIGRATION DOES NOT SEED THE ACCOUNT
  0003 seeds founders from env vars, so there is precedent — but a shared
  credential must be revocable without a deploy, and a migration that recreates
  the demo login on every `alembic upgrade head` would silently undo a
  revocation. Seeding is therefore a CLI step: `python -m app.cli seed-guest`.

WHY DOWNGRADE DEACTIVATES RATHER THAN JUST FOLDING
  0006's downgrade folds 'admin' -> 'founder', i.e. into a LESS privileged
  role. The same move is not available here: 'guest' is the least privileged
  role we have, so every fold target grants MORE access. Folding a guest row
  to 'customer' would silently promote a password that has been handed out in
  sales emails into a role that can reach customer data — a downgrade must not
  be able to escalate a credential.

  Deleting the row instead would destroy data (and break the FK'd session
  history), which is the other thing a downgrade must not do silently.

  So downgrade does both halves of the safe answer: it deactivates the guest
  rows first (is_active = false, which app.core.auth_deps.current_user and the
  login route both enforce on every request), deletes their live sessions so
  no issued cookie survives the change of role, and only then folds the role
  to 'customer' so the narrower CHECK can re-apply. The rows survive, nothing
  can log in with them, and re-running `seed-guest` after a re-upgrade
  restores the demo deliberately rather than by accident.
"""
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


# The role set on each side of this migration, in the order the constraint
# states them. Keep ROLES_AFTER in lockstep with app.models.user.ROLES.
ROLES_AFTER = ("admin", "founder", "customer", "investor", "guest")
ROLES_BEFORE = ("admin", "founder", "customer", "investor")

#: Where a deactivated guest row lands so the 0006-era CHECK can re-apply.
#: Safe only because the row is deactivated in the same statement block, and
#: that pair (this role + is_active=false) is what `app.cli seed-guest` matches
#: on to restore the account after a rollback. Keep in lockstep with
#: app.models.user.GUEST_DOWNGRADE_FOLD_ROLE.
DOWNGRADE_FOLD_ROLE = "customer"


def _recreate_role_check(roles: tuple[str, ...]) -> None:
    """Drop and recreate users_role_check over exactly `roles`.

    DDL is idempotent (DROP ... IF EXISTS) so it is safe against a database
    built from ORM metadata as well as one migrated 0001 -> 0006, matching
    0006's style.
    """
    literal = ", ".join(f"'{role}'" for role in roles)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        f"CHECK (role IN ({literal}))"
    )


def upgrade() -> None:
    _recreate_role_check(ROLES_AFTER)


def downgrade() -> None:
    # 1. Revoke before demoting. A guest row is about to become a 'customer'
    #    row; it must not be able to authenticate as one.
    op.execute("UPDATE users SET is_active = false WHERE role = 'guest'")
    # 2. Drop live sessions so no already-issued cookie survives the role change.
    op.execute(
        "DELETE FROM sessions WHERE user_id IN "
        "(SELECT id FROM users WHERE role = 'guest')"
    )
    # 3. Only now fold the role, so the stricter check can re-apply.
    op.execute(
        f"UPDATE users SET role = '{DOWNGRADE_FOLD_ROLE}' WHERE role = 'guest'"
    )
    _recreate_role_check(ROLES_BEFORE)
