"""The French verdicts the server writes into a command, shared with the console.

Since the bilingual console (plan ``dev/plan-console-bilingue.md``, I3), the
console words a verdict the server wrote — a command lost or cancelled, a
deployment refused, a wake refused or emitted — from the ``result_code`` and
``result_params`` stored beside the French text. Its French must stay the
sentence the server writes: an installation updated to this version reads the
same as before.

``tests/data/command_texts_fr.json`` holds the cases: this test checks the
server still writes them, ``frontend/src/services/commandResults.spec.ts`` that the
console writes the same from the codes. Regenerate it after a deliberate
change of wording with ``python -m tests.test_command_texts`` (run from
``backend/``, with ENVIRONMENT=local), and change the console's catalogue
(``frontend/src/i18n/messages/commands.ts``) to match.
"""

import json
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).parent / "data" / "command_texts_fr.json"


def _case(verdict) -> dict[str, Any]:
    return {"code": verdict.code, "params": verdict.params, "message": verdict.text}


def _no_destination(ip: str | None, prefix: int | None, allowed: list[str]):
    """The refusal the sender writes, with ``WOL_ALLOWED_NETWORKS`` set."""
    from app.core.config import settings
    from app.features.wol import sender

    original = settings.WOL_ALLOWED_NETWORKS
    settings.WOL_ALLOWED_NETWORKS = allowed
    try:
        return sender._no_destination(ip, prefix)
    finally:
        settings.WOL_ALLOWED_NETWORKS = original


def cases() -> list[dict[str, Any]]:
    from app.features.command import texts

    verdicts = [
        texts.unanswered(6),
        texts.unanswered(48),
        texts.merged(),
        texts.package_deleted(),
        texts.package_retired_after_queue(),
        texts.package_changed_after_queue(),
        texts.package_retired(),
        texts.package_superseded(),
        texts.wake_no_mac(),
        _no_destination(None, None, []),
        _no_destination("8.8.8.8", 24, []),
        _no_destination("10.4.7.5", None, ["10.4.7.0/25", "192.168.1.0/24"]),
        _no_destination("10.4.7.5", 16, ["10.4.7.0/24"]),
        texts.wake_send_failed("[Errno 101] Network is unreachable"),
        texts.wake_sent("AA:BB:CC:DD:EE:FF", 3, "10.4.7.255:9, 255.255.255.255:9"),
        texts.wake_sent("AA:BB:CC:DD:EE:FF", 1, "10.4.7.255:9"),
        texts.wake_no_site(),
        texts.wake_no_relay("location", "Lycée Victor Hugo"),
        texts.wake_no_relay("domain", "ac-test.local"),
        texts.wake_relay_queued("location", "Bâtiment A", 3, 10),
        texts.wake_relay_queued("domain", "ac-test.local", 1, 60),
        texts.wake_relay_already(True, 0),
        texts.wake_relay_already(False, 12),
        texts.wake_relay_already(True, 65),
        texts.wake_relay_already(False, 600),
        texts.wake_back_online(),
        texts.wake_unknown_machine(),
    ]
    return [_case(v) for v in verdicts]


def test_the_server_still_writes_the_shared_sentences():
    assert cases() == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_every_code_has_a_case():
    """Each verdict the server can write has a case, so the console's French
    is checked for all of them."""
    from app.features.command import texts

    makers = [
        name
        for name, value in vars(texts).items()
        if callable(value)
        and getattr(value, "__module__", None) == texts.__name__
        and not name.startswith("_")
        and name not in {"elapsed", "relayed", "clean_message", "Verdict"}
    ]
    covered = {c["code"] for c in cases()}
    assert len(covered) == len(makers)
    for name in makers:
        if name.startswith("wake_"):
            assert f"wol.{name.removeprefix('wake_')}" in covered, name


def test_the_texts_the_routes_wrote_before_are_unchanged():
    """The sentences that were constants stay, word for word."""
    from app.features.command import texts
    from app.features.machine.crud import MERGED_ERROR
    from app.features.package.crud import RETIRED_ERROR, SUPERSEDED_ERROR

    assert MERGED_ERROR == "Poste fusionné : commande annulée"
    assert RETIRED_ERROR == "Paquet retiré : installation annulée"
    assert SUPERSEDED_ERROR == "Remplacée par un nouveau déploiement"
    assert texts.unanswered(6).text == (
        "Sans réponse du poste 6 h après la remise : commande considérée comme "
        "perdue (poste éteint, agent arrêté ou mis à jour pendant l'exécution). "
        "Relancez-la si besoin."
    )
    assert texts.TRUNCATED_NOTE == "\n[…] sortie tronquée par le serveur"


def test_an_agent_message_is_kept_only_well_formed():
    from app.features.command.texts import clean_message

    assert clean_message("wol.relay.sent", {"mac": "aa", "copies": 3}) == (
        "wol.relay.sent",
        {"mac": "aa", "copies": 3},
    )
    assert clean_message("agent.stopped", None) == ("agent.stopped", {})
    assert clean_message(None, None) == (None, None)
    # Parameters without a code mean nothing.
    assert clean_message(None, {"a": 1}) == (None, None)
    for code in ["", "Agent.Stopped", "a b", "x" * 65, "é", 12, ["a"]]:
        assert clean_message(code, {}) == (None, None), code
    for params in [
        [1],
        "a",
        {"A": 1},
        {"1a": 1},
        {"a" * 33: 1},
        {"nested": {"a": 1}},
        {"list": [1, 2]},
        {"long": "x" * 1025},
        {"nan": float("nan")},
        {f"k{i}": i for i in range(17)},
        {f"k{i}": "x" * 1000 for i in range(5)},
    ]:
        assert clean_message("a.b", params) == (None, None), params
    assert clean_message("a.b", {"t": "x" * 1024, "n": None, "f": 1.5, "b": True}) == (
        "a.b",
        {"t": "x" * 1024, "n": None, "f": 1.5, "b": True},
    )


if __name__ == "__main__":
    FIXTURE.write_text(
        json.dumps(cases(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{len(cases())} cases written to {FIXTURE}")
