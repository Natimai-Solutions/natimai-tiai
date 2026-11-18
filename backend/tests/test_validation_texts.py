"""The French of every coded validation refusal, shared with the console.

``tests/data/validation_texts_fr.json`` holds, for each refusal of ours
(``core.validation.invalid``), its code, its parameters and its message as
the 422 says it after « Value error, »: this test checks the server still
writes them, ``frontend/src/services/validationTexts.spec.ts`` that the
console writes the same from the codes. Regenerate after a deliberate change
of wording with ``python -m tests.test_validation_texts`` (from ``backend/``,
ENVIRONMENT=local), and change the console's catalogue to match.
"""

import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ValidationError

FIXTURE = Path(__file__).parent / "data" / "validation_texts_fr.json"


def _refusals(model: type[BaseModel], data: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        model.model_validate(data)
    except ValidationError as exc:
        return [
            {
                "code": e["type"].removeprefix("tiai_"),
                "params": dict(e.get("ctx") or {}),
                "message": e["msg"].removeprefix("Value error, "),
            }
            for e in exc.errors()
            if e["type"].startswith("tiai_")
        ]
    raise AssertionError(f"{model.__name__} accepted {data!r}")


def cases() -> list[dict[str, Any]]:
    from app.api.fields import Password, bounded_name, not_null
    from app.api.routes.packages import PackageBody
    from app.api.routes.rooms import PlaceName
    from app.core.control_chars import NUL_REFUSED, TOO_NESTED
    from app.features.intervention.crud import PastDatetime

    class Account(BaseModel):
        name: Annotated[str | None, bounded_name(5)] = None
        password: Password | None = None
        _null = not_null("name", "email")

    class Place(BaseModel):
        name: PlaceName

    class Entry(BaseModel):
        at: PastDatetime

    out: list[dict[str, Any]] = []
    out += _refusals(Account, {"name": "   "})
    out += _refusals(Account, {"name": "abcdefgh"})
    out += _refusals(Account, {"name": None, "email": None})
    out += _refusals(Account, {"password": "é" * 60})
    out += _refusals(Place, {"name": "​"})
    out += _refusals(Entry, {"at": "2999-01-01T00:00:00Z"})
    out += _refusals(PackageBody, {"name": "a\x01"})
    out += _refusals(PackageBody, {"name": "x" * 201})
    out += _refusals(PackageBody, {"notes": "x" * 5001})
    out += _refusals(PackageBody, {"install_args": ["a"] * 65})
    out += _refusals(PackageBody, {"install_args": ["a" * 5000]})
    out += _refusals(PackageBody, {"install_args": None})
    out += _refusals(PackageBody, {"success_codes": []})
    out += _refusals(PackageBody, {"success_codes": [2**40]})
    out += _refusals(PackageBody, {"name": "  "})
    # Built by hand, not raised: the closing date, NUL and nesting refusals.
    out += [
        {
            "code": "date_before_request",
            "params": {},
            "message": "la date ne peut pas précéder la demande",
        },
        {"code": "nul_refused", "params": {}, "message": NUL_REFUSED},
        {"code": "too_nested", "params": {}, "message": TOO_NESTED},
    ]
    return out


def test_the_server_still_writes_the_shared_sentences():
    assert cases() == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_every_code_has_a_case():
    import re

    codes = set()
    for path in (Path(__file__).parents[1] / "app").rglob("*.py"):
        codes |= set(re.findall(r'invalid\(\s*"([a-z_]+)"', path.read_text()))
        codes |= set(
            re.findall(r'refusal\(\s*\[[^\]]*\],\s*"([a-z_]+)"', path.read_text())
        )
    codes |= {"nul_refused", "too_nested"}
    assert codes <= {c["code"] for c in cases()}


if __name__ == "__main__":
    FIXTURE.write_text(
        json.dumps(cases(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{len(cases())} cases written to {FIXTURE}")
