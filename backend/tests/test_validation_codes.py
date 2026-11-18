"""Validation refusals carry a code and its parameters (plan console bilingue).

The 422's ``msg`` stays the French sentence it always was (« Value error,
… »); ``type`` becomes ``tiai_<code>`` and ``params`` fills the sentence the
console words in its reader's language. Pydantic's own refusals are left as
they are.
"""

from typing import Annotated

import pytest
from pydantic import AfterValidator, BaseModel, ValidationError

from app.api.fields import Password, bounded_name, not_null
from app.core.validation import PREFIX, invalid, refusal
from app.features.intervention.crud import PastDatetime
from tests.test_api_packages import _admin


def _errors(model: type[BaseModel], data: dict) -> list[dict]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return caught.value.errors()


def test_a_refusal_keeps_its_message_and_gains_a_code():
    def no(value: str) -> str:
        raise invalid("x_y", "valeur « {a} » refusée", max=3)

    class M(BaseModel):
        a: Annotated[str, AfterValidator(no)]

    (error,) = _errors(M, {"a": "z"})
    assert error["type"] == f"{PREFIX}x_y"
    # Braces in a message are not placeholders: it is said as written.
    assert error["msg"] == "Value error, valeur « {a} » refusée"
    assert error["ctx"] == {"max": 3}
    assert refusal(["body", "a"], "x_y", "non", n=1) == {
        "loc": ["body", "a"],
        "msg": "Value error, non",
        "type": f"{PREFIX}x_y",
        "params": {"n": 1},
    }


def test_the_shared_fields_say_why_by_code():
    class Account(BaseModel):
        name: Annotated[str | None, bounded_name(5)] = None
        password: Password | None = None
        _null = not_null("name")

    errors = _errors(Account, {"name": "   "})
    assert errors[0]["type"] == f"{PREFIX}name_blank"
    errors = _errors(Account, {"name": "abcdefgh"})
    assert (errors[0]["type"], errors[0]["ctx"]) == (
        f"{PREFIX}name_too_long",
        {"max": 5, "length": 8},
    )
    assert (
        errors[0]["msg"]
        == "Value error, le nom ne doit pas dépasser 5 caractères (reçu : 8)"
    )
    errors = _errors(Account, {"name": None})
    assert (errors[0]["type"], errors[0]["ctx"]) == (
        f"{PREFIX}null_refused",
        {"fields": ["name"]},
    )
    errors = _errors(Account, {"password": "é" * 60})
    assert errors[0]["type"] == f"{PREFIX}password_too_long"

    class Entry(BaseModel):
        at: PastDatetime

    errors = _errors(Entry, {"at": "2999-01-01T00:00:00Z"})
    assert errors[0]["type"] == f"{PREFIX}date_in_future"
    assert errors[0]["msg"] == "Value error, la date ne peut pas être dans le futur"


async def test_the_422_hands_the_code_and_params_to_the_console(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "x" * 300},
    )
    assert resp.status_code == 422
    (error,) = resp.json()["error"]["details"]["errors"]
    assert error["type"] == f"{PREFIX}too_long"
    assert error["params"] == {"max": 200}
    assert error["msg"] == "Value error, 200 caractères au plus"

    # Pydantic's own refusal: no params, its type and message as before.
    resp = await client.post("/api/v1/packages", headers=admin, json={"name": "x"})
    (error,) = resp.json()["error"]["details"]["errors"]
    assert error["type"] == "missing"
    assert "params" not in error


async def test_a_nul_byte_is_refused_with_a_code(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/packages",
        headers={**admin, "content-type": "application/json"},
        content=b'{"kind": "files", "name": "a\\u0000b"}',
    )
    assert resp.status_code == 422
    (error,) = resp.json()["error"]["details"]["errors"]
    assert error["type"] == f"{PREFIX}nul_refused"
    assert error["msg"] == "Caractère nul refusé"
