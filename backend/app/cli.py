"""Admin CLI: create-user, reset-password, seed-guest.

Usage (one-off in production via `railway run`):
    python -m app.cli create-user --email a@b.com --name "Alex" --role founder
    python -m app.cli reset-password --email a@b.com
    CATALOG_GUEST_PASSWORD=... python -m app.cli seed-guest
    python -m app.cli seed-guest --deactivate        # kill switch

MIN_PASSWORD_LEN is 12 and stays 12 for every command here except
`seed-guest`, whose single, scoped exception is documented at
GUEST_MIN_PASSWORD_LEN below.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import delete, select, update

from app.core.db import get_sessionmaker
from app.core.passwords import hash_password
from app.models import Session as SessionRow, User
from app.models.user import (
    GUEST_DOWNGRADE_FOLD_ROLE,
    GUEST_EMAIL,
    GUEST_ROLE,
    ROLES,
)


# 'guest' is creatable here too, but only under the normal 12-character rule.
# That is the supported path for a PER-PROSPECT read-only account; the single
# shared demo credential is `seed-guest`'s job.
VALID_ROLES = set(ROLES)
MIN_PASSWORD_LEN = 12

# --------------------------------------------------------------------------- #
# The shared read-only demo account                                            #
# --------------------------------------------------------------------------- #

#: The documented exception to MIN_PASSWORD_LEN, and the only one.
#:
#: The credential we committed to handing prospects is nine characters, and
#: MIN_PASSWORD_LEN is twelve. The wrong fix is to lower MIN_PASSWORD_LEN:
#: that quietly weakens every founder, admin, customer and investor account in
#: order to buy one demo login. So the exception is made here, once, narrowly:
#:
#:   * it applies only to GUEST_EMAIL, and `seed-guest` refuses any other
#:     address, so it cannot be aimed at a real account by a typo;
#:   * it hardcodes role=guest, so it cannot mint a privileged account;
#:   * it prints the exception it is making, every time.
#:
#: The security argument is that the guest password is a SHARED credential, not a
#: per-person one: it goes to every prospect in a sales email, so its entropy
#: buys far less than it would for a real account. What protects us is that the
#: account is read-only server-side, absolutely capped at 8 hours per session
#: (app.core.auth_deps.GUEST_SESSION_TTL), and revocable in one command
#: (`seed-guest --deactivate`).
#:
#: "Shared" is NOT "public", and the difference is the whole control. This
#: repository is public: a password committed to it is readable by GitHub code
#: search, every fork and every CI log, permanently, and at that point the rate
#: limit and the 8-hour cap are all that is left. So the value lives in the
#: password manager, reaches this command only through $CATALOG_GUEST_PASSWORD
#: or the prompt, and appears nowhere in the tree — not in a doc, not as a test
#: default, not as a fallback in the e2e harness. See docs/catalog/DEPLOY.md §7.
#:
#: Eight is not a security judgement. It is the floor below which a truncated
#: paste or a stray shell quote becomes the more likely explanation.
GUEST_MIN_PASSWORD_LEN = 8

#: Preferred way to supply the password: a flag lands in shell history and in
#: `ps` output for every user on the box. `--password` exists for scripted
#: provisioning and warns when used.
GUEST_PASSWORD_ENV = "CATALOG_GUEST_PASSWORD"

GUEST_DISPLAY_NAME = "Guest (shared demo)"


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


def _assert_guest_email(email: str | None) -> str:
    """Refuse to touch anything but the reserved demo address."""
    target = (email or GUEST_EMAIL).strip().lower()
    if target != GUEST_EMAIL:
        raise ValueError(
            f"refusing to run against {target!r}: seed-guest only ever touches the "
            f"reserved demo account {GUEST_EMAIL!r}, because it is the only account "
            f"allowed a password shorter than {MIN_PASSWORD_LEN} chars. To create a "
            f"normal account use create-user."
        )
    return target


async def seed_guest(
    *,
    email: str | None = None,
    password: str | None = None,
    deactivate: bool = False,
) -> str:
    """Create, update or deactivate the shared read-only demo account.

    Changing the password also deletes every live guest session, exactly like
    `reset-password` does — that is what makes a rotation an actual revocation
    rather than a suggestion. `--deactivate` does the same and flips
    `is_active`, which `app.core.auth_deps.current_user` enforces on every
    request. Returns a one-line status for the caller to print.
    """
    target = _assert_guest_email(email)
    SessionLocal = get_sessionmaker()

    if deactivate:
        async with SessionLocal() as s:
            user = (await s.execute(select(User).where(User.email == target))).scalar_one_or_none()
            if user is None:
                raise ValueError(f"no guest account at {target}; nothing to deactivate")
            await s.execute(update(User).where(User.id == user.id).values(is_active=False))
            killed = await s.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
            await s.commit()
            return (
                f"guest access DISABLED for {target}; "
                f"{killed.rowcount or 0} live session(s) killed. "
                f"Re-enable by running seed-guest with a password again."
            )

    if password is None:
        raise ValueError("a password is required (pass --password, set "
                         f"${GUEST_PASSWORD_ENV}, or answer the prompt)")
    if len(password) < GUEST_MIN_PASSWORD_LEN:
        raise ValueError(
            f"guest password must be at least {GUEST_MIN_PASSWORD_LEN} chars "
            f"(the rule everywhere else is {MIN_PASSWORD_LEN}; this command "
            f"already relaxes it as far as it goes)"
        )

    async with SessionLocal() as s:
        existing = (await s.execute(select(User).where(User.email == target))).scalar_one_or_none()
        if existing is None:
            s.add(User(
                email=target,
                name=GUEST_DISPLAY_NAME,
                role=GUEST_ROLE,
                password_hash=hash_password(password),
                is_active=True,
            ))
            await s.commit()
            return f"created guest account {target} (role={GUEST_ROLE}, active)"

        # The one row that is not already a guest but may still be reseeded: the
        # artefact migration 0007's downgrade leaves behind. It folds the guest to
        # GUEST_DOWNGRADE_FOLD_ROLE *and* deactivates it in the same block, so the
        # pair is unambiguous -- a genuine customer at this address would be active.
        # Without this, a downgrade/re-upgrade cycle strands the demo account with no
        # recovery short of a hand-written DELETE, which is exactly what 0007 set out
        # to avoid. Anything else still refuses.
        rollback_artefact = (
            existing.role == GUEST_DOWNGRADE_FOLD_ROLE and not existing.is_active
        )
        if existing.role != GUEST_ROLE and not rollback_artefact:
            raise ValueError(
                f"{target} already exists with role={existing.role!r}. Refusing to "
                f"overwrite a non-guest account with the relaxed password rule; "
                f"delete that row deliberately first."
            )
        await s.execute(
            update(User)
            .where(User.id == existing.id)
            .values(
                password_hash=hash_password(password),
                is_active=True,
                role=GUEST_ROLE,
            )
        )
        killed = await s.execute(delete(SessionRow).where(SessionRow.user_id == existing.id))
        await s.commit()
        restored = " (restored from a 0007 downgrade)" if rollback_artefact else ""
        return (
            f"updated guest account {target} (role={GUEST_ROLE}, active){restored}; "
            f"{killed.rowcount or 0} live session(s) invalidated"
        )


def _prompt_password(label: str = "password") -> str:
    a = getpass.getpass(f"{label}: ")
    b = getpass.getpass(f"{label} (again): ")
    if a != b:
        raise SystemExit("passwords did not match")
    return a


def _guest_password(args: argparse.Namespace) -> str:
    if args.password:
        print(
            "warning: --password is visible in shell history and in `ps` output. "
            f"Prefer ${GUEST_PASSWORD_ENV} or the interactive prompt.",
            file=sys.stderr,
        )
        return args.password
    from_env = os.environ.get(GUEST_PASSWORD_ENV)
    if from_env:
        return from_env
    return _prompt_password("guest password")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-user")
    p_create.add_argument("--email", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--role", required=True, choices=sorted(VALID_ROLES))

    p_reset = sub.add_parser("reset-password")
    p_reset.add_argument("--email", required=True)

    p_guest = sub.add_parser(
        "seed-guest",
        help="create, rotate or deactivate the shared read-only demo account",
        description=(
            "Creates or updates the single shared guest account. This is the "
            f"ONLY command that accepts a password shorter than {MIN_PASSWORD_LEN} "
            f"characters (minimum {GUEST_MIN_PASSWORD_LEN}), and it does so only "
            f"for {GUEST_EMAIL}. Changing the password logs out every live guest "
            "session."
        ),
    )
    p_guest.add_argument(
        "--email",
        default=GUEST_EMAIL,
        help=f"must be {GUEST_EMAIL} (the default); any other value is refused",
    )
    p_guest.add_argument(
        "--password",
        default=None,
        help=f"prefer ${GUEST_PASSWORD_ENV} or the prompt — a flag leaks into `ps`",
    )
    p_guest.add_argument(
        "--deactivate",
        action="store_true",
        help="kill switch: deactivate the account and drop every live session",
    )

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
    if args.cmd == "seed-guest":
        try:
            password = None
            if not args.deactivate:
                _assert_guest_email(args.email)  # refuse before asking for a password
                password = _guest_password(args)
                print(
                    f"note: applying the documented password-length exception "
                    f"({GUEST_MIN_PASSWORD_LEN} chars, vs {MIN_PASSWORD_LEN} "
                    f"everywhere else) to {GUEST_EMAIL}. The guest credential is "
                    f"SHARED (one string, every prospect) but it is not public: "
                    f"keep it in the password manager and out of the repository. "
                    f"What protects us is that the account is read-only "
                    f"server-side and revocable with `seed-guest --deactivate`.",
                    file=sys.stderr,
                )
            message = asyncio.run(
                seed_guest(email=args.email, password=password, deactivate=args.deactivate)
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(message)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
