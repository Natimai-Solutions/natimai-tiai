"""Validation refusals the console words in its reader's language.

A field validator that refuses a value raises ``invalid(code, message,
**params)`` rather than a bare ``ValueError``: the 422 still carries the same
``msg`` (« Value error, <message> », in French, as it always did — for an
older console and for scripts), and gains a stable ``type`` (``tiai_<code>``)
and the ``params`` that fill the sentence, which the console words from its
catalogue (plan ``dev/plan-console-bilingue.md``; ``errors.validation`` in
``frontend/src/i18n/messages/errors.ts``).

Pydantic's own refusals (``missing``, ``string_too_long``…) keep their type
and their English message, as before.
"""

from typing import Any

from pydantic_core import PydanticCustomError

# What every code of ours starts with: never one of Pydantic's own types.
PREFIX = "tiai_"


def invalid(code: str, message: str, **params: Any) -> PydanticCustomError:
    """A refusal to raise from a validator. ``params`` must be JSON values
    (strings, numbers, lists of them): the 422 hands them to the console."""
    # The template is the whole message, already filled: Pydantic replaces
    # only ``{key}`` for a key of the context, and the messages name none.
    return PydanticCustomError(PREFIX + code, "Value error, " + message, params)


def refusal(loc: list[Any], code: str, message: str, **params: Any) -> dict[str, Any]:
    """One item of a 422's ``details.errors`` built by hand, as the handler
    renders a raised ``invalid``."""
    return {
        "loc": loc,
        "msg": "Value error, " + message,
        "type": PREFIX + code,
        "params": params,
    }
