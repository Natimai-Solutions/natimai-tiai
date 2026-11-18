"""The account's language (need a database) — Phase 6, bilingual console.

Null until the account chooses: the console then follows the browser, and
the mail sent to the account uses DEFAULT_LANGUAGE. An installation updated
to this version therefore sees what it saw before.
"""

from app.core.config import Settings
from tests.test_api_preferences import _login


async def test_an_account_starts_without_a_language(client, db_session):
    headers = await _login(client, db_session, "lang-fresh@test.local")
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["language"] is None


async def test_the_language_is_set_kept_and_cleared(client, db_session):
    headers = await _login(client, db_session, "lang-set@test.local")
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"language": "en"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["language"] == "en"

    # Another field changed alone: the language stays.
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"email_preference": "none"}
    )
    assert resp.json()["language"] == "en"
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"preferences": {"a": 1}}
    )
    assert resp.json()["language"] == "en"

    # Null: back to « follow the browser ».
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"language": None}
    )
    assert resp.json()["language"] is None
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["language"] is None


async def test_an_unknown_language_is_refused(client, db_session):
    headers = await _login(client, db_session, "lang-bad@test.local")
    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"language": "de"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "request.validation_error"


async def test_a_stored_value_that_is_no_language_reads_as_none(client, db_session):
    from sqlalchemy import update

    from app.features.user.models import User

    headers = await _login(client, db_session, "lang-hand@test.local")
    await db_session.exec(
        update(User).where(User.email == "lang-hand@test.local").values(language="xx")
    )
    await db_session.commit()
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["language"] is None


def test_mail_stays_french_unless_told_otherwise():
    assert Settings().DEFAULT_LANGUAGE == "fr"
    assert Settings(DEFAULT_LANGUAGE="en").DEFAULT_LANGUAGE == "en"


async def test_a_built_in_group_is_named_with_its_key(client, db_session):
    """The console names a built-in group in its reader's language while it
    keeps the name the installation gave it: it needs the group's key."""
    headers = await _login(client, db_session, "lang-groups@test.local")
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["groups"] == [
        {
            "id": me["groups"][0]["id"],
            "name": "Lecture seule",
            "builtin_key": "readonly",
        }
    ]
