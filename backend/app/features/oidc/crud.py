"""A sign-in through the directory, from start to account (C7).

``start`` records the attempt and builds the provider's URL; ``finish``
checks what comes back and answers with the account to open a session for:
the one already bound to this directory identity, a local account its holder
is linking from « Mon compte », or a new one — when the token carries at
least one directory group a Tia'i group stands for.

An account created here (``auth_source = 'oidc'``) has no password and its
groups follow the directory at each sign-in: the groups some directory group
maps to are recomputed, those given by hand in the console stay. A local
account, linked or not, keeps the groups the console gave it: the directory
never takes the console's last administrator away.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.features.base import utcnow
from app.features.oidc import client
from app.features.oidc.client import INVALID, OidcError
from app.features.oidc.models import OidcLogin
from app.features.user import crud as user_crud
from app.features.user.models import (
    Group,
    GroupIdpLink,
    User,
    UserGroup,
    normalize_email,
)

LOGIN_MINUTES = 10

# What the callback may end with, beside the provider's own failures.
NO_GROUP = "auth.oidc.no_group"
EMAIL_TAKEN = "auth.oidc.email_taken"
TOO_MANY_GROUPS = "auth.oidc.too_many_groups"
NO_EMAIL = "auth.oidc.no_email"
ACCOUNT_DISABLED = "auth.oidc.account_disabled"
ALREADY_LINKED = "auth.oidc.already_linked"
DENIED = "auth.oidc.denied"
CALLBACK_CODES = frozenset(
    {
        client.UNAVAILABLE,
        INVALID,
        NO_GROUP,
        EMAIL_TAKEN,
        TOO_MANY_GROUPS,
        NO_EMAIL,
        ACCOUNT_DISABLED,
        ALREADY_LINKED,
        DENIED,
    }
)

# A password nobody can type: bcrypt refuses to compare against it, and the
# login refuses the account before trying (``crud.authenticate``).
UNUSABLE_PASSWORD = "!oidc"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_redirect(value: str | None) -> str | None:
    """A path of the console, or None: never another site."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(c) < 32 for c in value) or len(value) > 2000:
        return None
    return value


async def start(
    session: AsyncSession,
    *,
    redirect: str | None,
    link_user_id: uuid.UUID | None = None,
) -> tuple[str, str]:
    """Record an attempt; returns the provider's URL and the browser token to
    set as a cookie. Commits."""
    state = secrets.token_urlsafe(32)
    browser = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = client.new_pkce()
    url = await client.authorize_url(state, nonce, challenge)
    now = utcnow()
    session.add(
        OidcLogin(
            state_hash=_hash(state),
            browser_hash=_hash(browser),
            nonce=nonce,
            code_verifier=verifier,
            redirect=safe_redirect(redirect),
            link_user_id=link_user_id,
            created_at=now,
            expires_at=now + timedelta(minutes=LOGIN_MINUTES),
        )
    )
    await session.commit()
    return url, browser


class NoGroupLeft(OidcError):
    """An account of the directory no longer in any mapped group: refused,
    its mapped groups removed (to commit and audit)."""

    def __init__(self, user: User, removed: list[str]) -> None:
        super().__init__(NO_GROUP, "no mapped group any more")
        self.user = user
        self.removed = removed


@dataclass
class Result:
    user: User
    redirect: str | None
    # What the sign-in did, for the audit: provisioned, linked, groups.
    provisioned: bool = False
    linked: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


async def _consume(session: AsyncSession, state: str, browser: str | None) -> OidcLogin:
    row = (
        await session.exec(
            select(OidcLogin)
            .where(col(OidcLogin.state_hash) == _hash(state))
            .with_for_update()
        )
    ).one_or_none()
    now = utcnow()
    if (
        row is None
        or row.used_at is not None
        or row.expires_at <= now
        or browser is None
        or not secrets.compare_digest(row.browser_hash, _hash(browser))
    ):
        raise OidcError(INVALID, "unknown, expired, spent or foreign sign-in")
    row.used_at = now
    session.add(row)
    return row


def _directory_groups(claims: dict[str, Any]) -> set[str]:
    from app.core.config import settings

    names = claims.get("_claim_names")
    if claims.get("hasgroups") or (
        isinstance(names, dict) and settings.OIDC_GROUPS_CLAIM in names
    ):
        raise OidcError(TOO_MANY_GROUPS, "group overage")
    value = claims.get(settings.OIDC_GROUPS_CLAIM, [])
    if not isinstance(value, list):
        return set()
    return {str(v).lower() for v in value if isinstance(v, str) and v}


async def linked_groups(session: AsyncSession) -> dict[uuid.UUID, set[str]]:
    rows = await session.exec(select(GroupIdpLink))
    out: dict[uuid.UUID, set[str]] = {}
    for link in rows.all():
        out.setdefault(link.group_id, set()).add(link.idp_group_id.lower())
    return out


async def _sync_groups(
    session: AsyncSession, user: User, directory: set[str]
) -> tuple[list[str], list[str], bool]:
    """Recompute the groups the directory decides; returns the names added,
    removed, and whether one mapped group at least is held."""
    links = await linked_groups(session)
    mapped = {gid for gid, ids in links.items() if ids & directory}
    current = set(
        (
            await session.exec(
                select(col(UserGroup.group_id)).where(col(UserGroup.user_id) == user.id)
            )
        ).all()
    )
    wanted = (current - set(links)) | mapped
    names = {
        g.id: g.name
        for g in (
            await session.exec(select(Group).where(col(Group.id).in_(current | wanted)))
        ).all()
    }
    added = sorted(names.get(g, str(g)) for g in wanted - current)
    removed = sorted(names.get(g, str(g)) for g in current - wanted)
    if wanted != current:
        await user_crud.set_user_groups(session, user, wanted)
    return added, removed, bool(mapped)


def _email(claims: dict[str, Any]) -> str | None:
    for key in ("email", "preferred_username", "upn"):
        value = claims.get(key)
        if isinstance(value, str) and "@" in value and len(value) <= 255:
            return normalize_email(value)
    return None


async def finish(
    session: AsyncSession, *, state: str, code: str, browser: str | None
) -> Result:
    """Check the provider's answer and find, link or create the account.
    Does not commit: the caller opens the session and commits."""
    row = await _consume(session, state, browser)
    redirect = row.redirect
    link_user_id = row.link_user_id
    nonce = row.nonce
    verifier = row.code_verifier
    id_token = await client.exchange(code, verifier)
    claims = await client.verify(id_token, nonce)
    issuer = client.issuer()
    subject = str(claims["sub"])

    bound = (
        await session.exec(
            select(User).where(
                col(User.oidc_issuer) == issuer, col(User.oidc_subject) == subject
            )
        )
    ).one_or_none()

    if link_user_id is not None:
        # « Associer mon compte » from a local account signed in by password.
        if bound is not None and bound.id != link_user_id:
            raise OidcError(ALREADY_LINKED, "identity bound to another account")
        user = await session.get(User, link_user_id)
        if user is None or not user.is_active:
            raise OidcError(ACCOUNT_DISABLED, "account gone or disabled")
        user.oidc_issuer = issuer
        user.oidc_subject = subject
        user.updated_at = utcnow()
        session.add(user)
        return Result(user=user, redirect=redirect, linked=True)

    directory = _directory_groups(claims)
    if bound is not None:
        if not bound.is_active:
            raise OidcError(ACCOUNT_DISABLED, "account disabled")
        if bound.auth_source != "oidc":
            # A linked local account: its groups are the console's.
            return Result(user=bound, redirect=redirect)
        added, removed, any_mapped = await _sync_groups(session, bound, directory)
        if not any_mapped:
            # Out of every mapped group: no access — and the groups the
            # directory took away are gone, which the caller commits.
            raise NoGroupLeft(bound, removed)
        return Result(user=bound, redirect=redirect, added=added, removed=removed)

    # First sign-in of this identity: an account, if a group says so.
    links = await linked_groups(session)
    if not any(ids & directory for ids in links.values()):
        raise OidcError(NO_GROUP, "no mapped group")
    email = _email(claims)
    if email is None:
        raise OidcError(NO_EMAIL, "no address in the token")
    if await user_crud.get_by_email(session, email) is not None:
        raise OidcError(EMAIL_TAKEN, "an account has this address")
    name = claims.get("name")
    user = User(
        email=email,
        hashed_password=UNUSABLE_PASSWORD,
        full_name=name[:255] if isinstance(name, str) and name else None,
        auth_source="oidc",
        oidc_issuer=issuer,
        oidc_subject=subject,
    )
    session.add(user)
    await session.flush()
    added, removed, _ = await _sync_groups(session, user, directory)
    return Result(user=user, redirect=redirect, provisioned=True, added=added)


async def purge(session: AsyncSession) -> int:
    """Drop the attempts that can no longer finish. Commits."""
    from sqlalchemy import delete, or_

    now = utcnow()
    result = await session.exec(
        delete(OidcLogin).where(
            or_(col(OidcLogin.expires_at) <= now, col(OidcLogin.used_at).is_not(None))
        )
    )
    await session.commit()
    return result.rowcount or 0
