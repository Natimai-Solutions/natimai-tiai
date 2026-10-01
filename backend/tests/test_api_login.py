"""Logging in: addresses compared whatever their case, and refusals that take
as long as successes.

The DB-backed tests require TIAI_TEST_DATABASE_URL; the unit tests at the
bottom always run.
"""

import pytest
from sqlalchemy.exc import IntegrityError

STRONG = "correct-horse-battery"


async def _login(client, email, password=STRONG):
    return await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )


async def _admin(client, db_session):
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.ensure_builtin_groups(db_session)
    await db_session.commit()
    await crud.create_user(
        db_session,
        email="admin@test.local",
        password=STRONG,
        groups=[BuiltinGroup.ADMIN],
    )
    resp = await _login(client, "admin@test.local")
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- E-mail addresses, whatever their case ------------------------------------


async def test_an_account_created_with_capitals_is_stored_lower_case(
    client, db_session
):
    headers = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "Jean.Dupont@Ecole.Local", "password": STRONG},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "jean.dupont@ecole.local"


@pytest.mark.parametrize(
    "typed",
    ["jean@ecole.local", "JEAN@ECOLE.LOCAL", "Jean@Ecole.local", " jean@ecole.local "],
)
async def test_login_ignores_the_case_of_the_address(client, db_session, typed):
    from app.features.user import crud

    await crud.create_user(db_session, email="Jean@Ecole.local", password=STRONG)
    resp = await _login(client, typed)
    assert resp.status_code == 200, resp.text


async def test_an_address_differing_only_by_case_is_taken(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "ADMIN@test.local", "password": STRONG},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "user.email.taken"


async def test_an_updated_address_is_normalised_and_checked(client, db_session):
    from app.features.user import crud

    headers = await _admin(client, db_session)
    other = await crud.create_user(
        db_session, email="other@test.local", password=STRONG
    )
    other_id = str(other.id)

    resp = await client.patch(
        f"/api/v1/users/{other_id}", headers=headers, json={"email": "Admin@Test.Local"}
    )
    assert resp.status_code == 409
    resp = await client.patch(
        f"/api/v1/users/{other_id}", headers=headers, json={"email": "New@Test.Local"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@test.local"


async def test_a_reset_request_finds_the_account_whatever_the_case(client, db_session):
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    await crud.create_user(db_session, email="jean@ecole.local", password=STRONG)
    resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "JEAN@Ecole.Local"}
    )
    assert resp.status_code == 204
    assert len((await db_session.exec(select(PasswordResetToken))).all()) == 1


async def test_the_database_refuses_two_spellings_of_one_address(db_session):
    """The rule holds below the API too: a row written by any other path is
    refused by the index on lower(email)."""
    from app.features.user.models import User

    db_session.add(User(email="dup@test.local", hashed_password="x"))
    await db_session.commit()
    db_session.add(User(email="DUP@test.local", hashed_password="x"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_get_by_email_ignores_case(db_session):
    from app.features.user import crud

    await crud.create_user(db_session, email="Mixed@Case.Local", password=STRONG)
    for typed in ("mixed@case.local", "MIXED@CASE.LOCAL"):
        user = await crud.get_by_email(db_session, typed)
        assert user is not None and user.email == "mixed@case.local"


# --- Refusals in constant time --------------------------------------------------


@pytest.fixture
def password_checks(monkeypatch):
    """Record every bcrypt verification the login path makes."""
    from app.core import security

    calls: list[str] = []
    real = security.verify_password

    def spy(plain: str, hashed: str) -> bool:
        calls.append(hashed)
        return real(plain, hashed)

    monkeypatch.setattr(security, "verify_password", spy)
    return calls


async def test_an_unknown_address_still_costs_a_password_check(
    client, db_session, password_checks
):
    from app.core import security

    resp = await _login(client, "nobody@test.local")
    assert resp.status_code == 401
    assert password_checks == [security.DUMMY_PASSWORD_HASH]


async def test_a_deactivated_account_still_costs_a_password_check(
    client, db_session, password_checks
):
    from app.core import security
    from app.features.user import crud

    user = await crud.create_user(db_session, email="gone@test.local", password=STRONG)
    user.is_active = False
    db_session.add(user)
    await db_session.commit()

    # Even with the right password: the answer and its cost are those of a
    # wrong one.
    resp = await _login(client, "gone@test.local")
    assert resp.status_code == 401
    assert password_checks == [security.DUMMY_PASSWORD_HASH]


async def test_every_refusal_reads_the_same(client, db_session, password_checks):
    from app.features.user import crud

    await crud.create_user(db_session, email="real@test.local", password=STRONG)
    unknown = await _login(client, "nobody@test.local")
    wrong = await _login(client, "real@test.local", "wrong-password-here")
    assert unknown.json() == wrong.json()
    assert len(password_checks) == 2
    assert password_checks[1] != password_checks[0]


# --- Unit ------------------------------------------------------------------------


def test_normalize_email_trims_and_lowers():
    from app.features.user.models import normalize_email

    assert normalize_email("  Jean.Dupont@Ecole.LOCAL ") == "jean.dupont@ecole.local"


def test_the_email_field_lowers_what_it_accepts():
    from pydantic import TypeAdapter

    from app.api.fields import Email

    assert TypeAdapter(Email).validate_python("A@B.Local") == "a@b.local"
