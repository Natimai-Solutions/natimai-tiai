"""The second factor (C7): enrolment, backup codes, the login challenge.

A right password for an account with a second factor opens no session: it
buys a challenge (``login_challenges``), redeemed by a code within
SECOND_FACTOR_CHALLENGE_MINUTES. Nothing in it reads the API.

The lock: SECOND_FACTOR_MAX_FAILED_ATTEMPTS wrong codes in a row, on any
challenge, lock the account's second factor for LOGIN_LOCKOUT_MINUTES —
counted on the account, since a fresh password login gives a fresh challenge
and must not give a fresh budget against the million codes. The password
having been proven, the address siege rule of the password lock does not
apply here: whoever is guessing codes already holds the password, and the
right answer to that is the lock and an audited trace.

Row locks follow ``crud.lock_account``'s order: the challenge (no account
rows depend on it), then the account.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secretbox, security, totp
from app.core.config import settings
from app.features.auth_session.models import (
    IP_MAX_LENGTH,
    USER_AGENT_MAX_LENGTH,
    LoginChallenge,
)
from app.features.base import utcnow
from app.features.user.models import Group, User, UserBackupCode, UserGroup

# Codes tried on one challenge at most: past that, start again from the
# password. The account's own counter is what bounds the guessing.
CHALLENGE_MAX_ATTEMPTS = 5
ISSUER = "Tia'i"


def enabled(user: User) -> bool:
    return user.totp_enabled_at is not None and user.totp_secret is not None


async def required(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether one of the account's groups requires a second factor."""
    found = await session.scalar(
        select(
            exists().where(
                col(UserGroup.user_id) == user_id,
                col(UserGroup.group_id) == col(Group.id),
                col(Group.mfa_required).is_(True),
            )
        )
    )
    return bool(found)


def locked(user: User, now: datetime) -> bool:
    return user.totp_locked_until is not None and user.totp_locked_until > now


# --- The login challenge ----------------------------------------------------


async def issue_challenge(
    session: AsyncSession, user: User, *, ip: str | None, user_agent: str | None
) -> str:
    """A challenge for a right password; returns the clear token. Does not
    commit."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    session.add(
        LoginChallenge(
            user_id=user.id,
            token_hash=security.hash_token(token),
            password_changed_at=user.password_changed_at,
            ip=(ip or "")[:IP_MAX_LENGTH] or None,
            user_agent=(user_agent or "")[:USER_AGENT_MAX_LENGTH] or None,
            created_at=now,
            expires_at=now
            + timedelta(minutes=settings.SECOND_FACTOR_CHALLENGE_MINUTES),
        )
    )
    await session.flush()
    return token


@dataclass
class Outcome:
    """What a code typed on a challenge came to."""

    # The account, when the code was right — the session can open.
    user: User | None = None
    # A backup code was spent (audited by the route).
    used_backup: bool = False
    # This failure locked the account's second factor (audited).
    just_locked: bool = False
    # The account whose code was wrong, for the audit and the log.
    failed_user: User | None = None


async def _codes_left(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(UserBackupCode)
            .where(
                col(UserBackupCode.user_id) == user_id,
                col(UserBackupCode.used_at).is_(None),
            )
        )
        or 0
    )


async def backup_codes_left(session: AsyncSession, user_id: uuid.UUID) -> int:
    return await _codes_left(session, user_id)


async def spend_backup_code(
    session: AsyncSession, user_id: uuid.UUID, typed: str, now: datetime
) -> bool:
    normalised = totp.normalise_backup_code(typed)
    if normalised is None:
        return False
    result = await session.exec(
        update(UserBackupCode)
        .where(
            col(UserBackupCode.user_id) == user_id,
            col(UserBackupCode.code_hash) == totp.hash_backup_code(normalised),
            col(UserBackupCode.used_at).is_(None),
        )
        .values(used_at=now)
        .returning(col(UserBackupCode.id))
    )
    return result.first() is not None


def check_code(user: User, code: str, now: datetime) -> int | None:
    """The TOTP step ``code`` matches for this account, or None (wrong,
    replayed, or a secret that can no longer be read)."""
    if user.totp_secret is None:
        return None
    secret = secretbox.decrypt_totp(user.totp_secret)
    if secret is None:
        return None
    return totp.matching_step(secret, code, now.timestamp(), after=user.totp_last_step)


def _note_wrong(user: User, now: datetime) -> bool:
    """Count a wrong code; True when it locks the second factor."""
    user.totp_failed_attempts += 1
    if user.totp_failed_attempts >= settings.SECOND_FACTOR_MAX_FAILED_ATTEMPTS:
        user.totp_failed_attempts = 0
        user.totp_locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        return True
    return False


async def redeem(session: AsyncSession, token: str, code: str) -> Outcome:
    """Check a code against a challenge. Does not commit: the caller commits
    the counters whatever the outcome, and opens the session on success.

    Every refusal looks the same to the caller — an unknown, expired, spent
    or exhausted challenge, a locked second factor, a wrong code — so the
    answer says nothing an attacker holding the password could use.
    """
    now = utcnow()
    challenge = (
        await session.exec(
            select(LoginChallenge)
            .where(col(LoginChallenge.token_hash) == security.hash_token(token))
            .with_for_update()
        )
    ).one_or_none()
    if (
        challenge is None
        or challenge.used_at is not None
        or challenge.expires_at <= now
        or challenge.attempts >= CHALLENGE_MAX_ATTEMPTS
    ):
        return Outcome()
    challenge.attempts += 1
    session.add(challenge)
    user = (
        await session.exec(
            select(User)
            .where(col(User.id) == challenge.user_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if (
        user is None
        or not user.is_active
        or not enabled(user)
        or user.password_changed_at != challenge.password_changed_at
    ):
        challenge.used_at = now
        return Outcome()
    if locked(user, now):
        return Outcome(failed_user=user)

    step = check_code(user, code, now)
    used_backup = False
    if step is None:
        used_backup = await spend_backup_code(session, user.id, code, now)
    if step is None and not used_backup:
        just_locked = _note_wrong(user, now)
        session.add(user)
        return Outcome(just_locked=just_locked, failed_user=user)

    if step is not None:
        user.totp_last_step = step
    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    session.add(user)
    challenge.used_at = now
    return Outcome(user=user, used_backup=used_backup)


async def purge_challenges(session: AsyncSession) -> int:
    """Drop the challenges that can no longer open anything. Commits."""
    now = utcnow()
    result = await session.exec(
        delete(LoginChallenge).where(
            (col(LoginChallenge.expires_at) <= now)
            | col(LoginChallenge.used_at).is_not(None)
        )
    )
    await session.commit()
    return result.rowcount or 0


# --- Enrolment, from « Mon compte » ------------------------------------------


def start_enrolment(user: User) -> tuple[str, str]:
    """A fresh pending secret on the account; returns it and its otpauth URI.

    Replaces a pending one (a QR code scanned on a phone since lost), never
    a confirmed one: the caller refuses that."""
    secret = totp.new_secret()
    user.totp_secret = secretbox.encrypt_totp(secret)
    user.totp_enabled_at = None
    user.totp_last_step = None
    return secret, totp.otpauth_uri(secret, user.email, ISSUER)


async def new_backup_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Ten fresh codes; the previous ones stop working. Does not commit."""
    await session.exec(
        delete(UserBackupCode).where(col(UserBackupCode.user_id) == user_id)
    )
    codes = totp.new_backup_codes()
    now = utcnow()
    for code in codes:
        session.add(
            UserBackupCode(
                user_id=user_id,
                code_hash=totp.hash_backup_code(code.replace("-", "")),
                created_at=now,
            )
        )
    await session.flush()
    return codes


async def clear(session: AsyncSession, user: User) -> None:
    """Remove the account's second factor and its backup codes. Does not
    commit."""
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    session.add(user)
    await session.exec(
        delete(UserBackupCode).where(col(UserBackupCode.user_id) == user.id)
    )
