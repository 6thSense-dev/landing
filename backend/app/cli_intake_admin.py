"""Explicit operator-only provisioning for Ronak's existing portal identity.

Run on the backend host: python -m app.cli_intake_admin
Existing passwords are preserved. New accounts require a hidden password prompt.
No HTTP endpoint or login-triggered role changes are installed.
"""
from __future__ import annotations

import asyncio
import getpass

from sqlalchemy import delete, func, select

from app.cli import MIN_PASSWORD_LEN
from app.core.db import get_sessionmaker
from app.core.passwords import hash_password
from app.models import Session as SessionRow, User

EMAIL = "ronak@6thsense.dev"


async def provision(*, new_password: str | None = None) -> str:
    async with get_sessionmaker()() as session:
        # Serialize concurrent provisioning, including the absent-row case.
        await session.execute(select(func.pg_advisory_xact_lock(61911001)))
        users = (await session.execute(
            select(User).where(func.lower(User.email) == EMAIL).with_for_update()
        )).scalars().all()
        if len(users) > 1:
            raise ValueError("Multiple case variants of Ronak's account exist; resolve identity first.")
        if not users:
            if new_password is None:
                raise ValueError("Account does not exist; provide a new password through the hidden prompt.")
            if len(new_password) < MIN_PASSWORD_LEN:
                raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
            session.add(User(email=EMAIL, name="Ronak", role="admin", is_active=True,
                             password_hash=hash_password(new_password)))
            outcome = "Created Ronak's admin account. Sign in through the existing portal."
        else:
            user = users[0]
            if user.email != EMAIL:
                raise ValueError("Existing email is not canonical lowercase; resolve identity before provisioning.")
            if not user.is_active:
                raise ValueError("Existing account is inactive; activation must be resolved explicitly.")
            if new_password is not None:
                raise ValueError("Existing password is preserved; use the existing reset-password command separately.")
            if user.role == "admin":
                return "Ronak's account is already admin; no changes made."
            user.role = "admin"
            # A previously issued session must not silently acquire more privilege.
            await session.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
            outcome = "Promoted Ronak to admin; old sessions revoked. Sign in again with the existing password."
        await session.commit()
        return outcome


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="Prompt for a password to create an absent account.")
    args = parser.parse_args()
    password = None
    if args.create:
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Confirm new password: "):
            parser.error("Passwords did not match.")
    try:
        print(asyncio.run(provision(new_password=password)))
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
