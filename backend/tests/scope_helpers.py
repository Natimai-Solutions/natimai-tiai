"""Shared fixtures for the location-scope tests (``user/scope.py``).

Two sites, one poste on each, and an account confined to the first: what every
scoped route is checked against — the poste of the other site must be absent
from lists and aggregates, and answer 404 when named.
"""

import uuid
from dataclasses import dataclass
from types import SimpleNamespace

from app.features.user.permissions import ALL_PERMISSIONS
from app.features.user.scope import Scope

STRONG = "correct-horse-battery"
SITE_A = "Lycée A"
SITE_B = "Lycée B"


async def login(client, email, password=STRONG):
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def group(db_session, name, permissions, scope: Scope | None):
    """A composed group, written straight to the database."""
    from app.features.user import crud
    from app.features.user.models import Group

    g = Group(name=name)
    db_session.add(g)
    await db_session.flush()
    await crud.set_group_permissions(db_session, g, permissions)
    await crud.set_group_scope(db_session, g, scope)
    await db_session.commit()
    await db_session.refresh(g)
    return SimpleNamespace(id=g.id)


async def account(client, db_session, email, groups):
    """An account in ``groups`` (ids or built-in keys), logged in."""
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=STRONG, groups=groups)
    return await login(client, email)


async def machine(db_session, hostname, location=None, room_id=None, **fields):
    from app.features.machine.models import Machine

    m = Machine(
        machine_uuid=str(uuid.uuid4()),
        hostname=hostname,
        location=location,
        room_id=room_id,
        **fields,
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    # A snapshot, not the ORM row: every later commit in the test expires the
    # row, and reading ``.id`` off it then is lazy I/O outside the event loop.
    return SimpleNamespace(id=m.id, machine_uuid=m.machine_uuid, hostname=m.hostname)


@dataclass
class TwoSites:
    """The usual fixture: ``a`` on site A, ``b`` on site B, ``scoped`` sees A
    only with every permission, ``admin`` sees both."""

    a: object
    b: object
    scoped: dict
    admin: dict


async def two_sites(client, db_session, *, permissions=ALL_PERMISSIONS):
    from app.features.user.permissions import BuiltinGroup

    a = await machine(db_session, "PC-A", location=SITE_A)
    b = await machine(db_session, "PC-B", location=SITE_B)
    g = await group(
        db_session, "Site A", permissions, Scope(locations=frozenset({SITE_A}))
    )
    scoped = await account(client, db_session, "tech-a@test.local", [g.id])
    admin = await account(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])
    return TwoSites(a=a, b=b, scoped=scoped, admin=admin)
