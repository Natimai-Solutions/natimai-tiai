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


def readable(user: User) -> bool:
    return user.totp_secret is not None and (
        secretbox.decrypt_totp(user.totp_secret) is not None
    )


def check_code(user: User, code: str, now: datetime) -> int | None:
    """The TOTP step ``code`` matches for this account, or None (wrong,
    replayed, or a secret that can no longer be read)."""
    if user.totp_secret is None:
        return None
    secret = secretbox.decrypt_totp(user.totp_secret)
    if secret is None:
        return None
    return totp.matching_step(secret, code, now.timestamp(), after=user.totp_last_step)


# The longest a lock lasts, however many came before it.
MAX_LOCK = timedelta(hours=24)


def _note_wrong(user: User, now: datetime) -> bool:
    """Count a wrong code; True when it locks the second factor.

    The count is not reset by a lock, only by a right code: every
    SECOND_FACTOR_MAX_FAILED_ATTEMPTS wrong codes lock it again, each time
    twice as long (LOGIN_LOCKOUT_MINUTES, then twice that…, 24 hours at
    most). Five guesses every fifteen minutes for ever would be ten
    thousand a month; doubling the wait leaves a few dozen."""
    user.totp_failed_attempts += 1
    limit = settings.SECOND_FACTOR_MAX_FAILED_ATTEMPTS
    if user.totp_failed_attempts % limit == 0:
        rounds = user.totp_failed_attempts // limit
        length = timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES) * 2 ** min(
            rounds - 1, 20
        )
        user.totp_locked_until = now + min(length, MAX_LOCK)
        return True
    return False


@dataclass
class Check:
    """A code checked against an account's second factor."""

    ok: bool = False
    used_backup: bool = False
    just_locked: bool = False
    locked: bool = False


async def verify_code(
    session: AsyncSession,
    user: User,
    code: str,
    now: datetime,
    *,
    allow_backup: bool = True,
) -> Check:
    """Check a code typed for an account — at login, or in « Mon compte » to
    disable the second factor or renew the backup codes. One place, so that
    every path counts towards the same lock and none guesses around it.
    The caller holds the account's row lock and commits the counters
    whatever the outcome."""
    if locked(user, now):
        return Check(locked=True)
    step = check_code(user, code, now)
    used_backup = False
    if step is None and allow_backup:
        used_backup = await spend_backup_code(session, user.id, code, now)
    if step is None and not used_backup:
        if not readable(user):
            # The secret can no longer be read (the key changed): no code
            # can match it, so none is counted — the backup codes stay
            # usable instead of being locked away by the app's codes.
            return Check()
        just_locked = _note_wrong(user, now)
        session.add(user)
        return Check(just_locked=just_locked)
    if step is not None:
        user.totp_last_step = step
    # A secret still sealed under the key before TOTP_ENCRYPTION_KEY: sealed
    # again under the current one, now that it was read.
    if user.totp_secret is not None and secretbox.totp_needs_resealing(
        user.totp_secret
    ):
        plain = secretbox.decrypt_totp(user.totp_secret)
        if plain is not None:
            user.totp_secret = secretbox.encrypt_totp(plain)
    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    session.add(user)
    return Check(ok=True, used_backup=used_backup)


async def enforce_on_members(session: AsyncSession, user_ids: list[uuid.UUID]) -> int:
    """Narrow to enrolment the live password sessions of the accounts that a
    group now requires a second factor of and that have none: the
    obligation applies at once, not at their next login. Does not commit."""
    if not user_ids:
        return 0
    from app.features.auth_session.models import AuthSession

    required_ids = [uid for uid in user_ids if await required(session, uid)]
    if not required_ids:
        return 0
    without = select(col(User.id)).where(
        col(User.id).in_(required_ids),
        col(User.totp_enabled_at).is_(None),
    )
    result = await session.exec(
        update(AuthSession)
        .where(
            col(AuthSession.user_id).in_(without),
            col(AuthSession.revoked_at).is_(None),
            col(AuthSession.auth_method) == "password",
            col(AuthSession.enrolment_only).is_(False),
        )
        .values(enrolment_only=True)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount or 0


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
    checked = await verify_code(session, user, code, now)
    if not checked.ok:
        return Outcome(just_locked=checked.just_locked, failed_user=user)
    challenge.used_at = now
    return Outcome(user=user, used_backup=checked.used_backup)


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
