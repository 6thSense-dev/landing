"""Admin CLI: create-user, reset-password.

Usage (one-off in production via `railway run`):
    python -m app.cli create-user --email a@b.com --name "Alex" --role founder
    python -m app.cli reset-password --email a@b.com
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import delete, select, update

from app.core.db import get_sessionmaker
from app.core.passwords import hash_password
from app.models import Session as SessionRow, User


VALID_ROLES = {"founder", "customer", "investor"}
MIN_PASSWORD_LEN = 12


async def create_user(*, email: str, name: str, role: str, password: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} chars")
    SessionLocal = get_sessionmaker()
    async with SessionLocal() as s:
        existing = (await s.execute(select(User).where(User.email == email.lower().strip()))).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"user with email {email} already exists")
        s.add(User(
            email=email.lower().strip(),
            name=name.strip(),
            role=role,
            password_hash=hash_password(password),
        ))
        await s.commit()


async def reset_password(*, email: str, new_password: str) -> None:
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} chars")
    SessionLocal = get_sessionmaker()
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.email == email.lower().strip()))).scalar_one_or_none()
        if user is None:
            raise ValueError(f"no user with email {email}")
        await s.execute(
            update(User).where(User.id == user.id).values(password_hash=hash_password(new_password))
        )
        await s.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
        await s.commit()


def _prompt_password(label: str = "password") -> str:
    a = getpass.getpass(f"{label}: ")
    b = getpass.getpass(f"{label} (again): ")
    if a != b:
        raise SystemExit("passwords did not match")
    return a


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-user")
    p_create.add_argument("--email", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--role", required=True, choices=sorted(VALID_ROLES))

    p_reset = sub.add_parser("reset-password")
    p_reset.add_argument("--email", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "create-user":
        pw = _prompt_password()
        try:
            asyncio.run(create_user(email=args.email, name=args.name, role=args.role, password=pw))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"created user {args.email}")
        return 0
    if args.cmd == "reset-password":
        pw = _prompt_password("new password")
        try:
            asyncio.run(reset_password(email=args.email, new_password=pw))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"password reset for {args.email}; all sessions invalidated")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
