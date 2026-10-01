"""What a bulk dispatch targeted, as the audit log records it.

A command row answers "who asked this poste for that" (``created_by``), and
that is enough for one poste. A broadcast leaves N such rows and nothing that
says what was *asked*: "every poste of the domain LYCEE" and "these
forty-two postes" produce the same rows, the postes skipped because they
already had the command produce none at all, and a filter that matched nobody
leaves no trace whatsoever. The ``command.bulk`` and ``machine.wake_bulk``
entries keep the request itself.
"""

import uuid
from typing import Any

from app.features.machine.status import MachineStatus


def describe_command_target(
    *,
    machine_ids: list[uuid.UUID] | None,
    target_all: bool,
    target_domain: str | None,
    target_location: str | None,
    target_status: MachineStatus | None,
) -> dict[str, Any] | None:
    """The target of a ``POST /commands``, or None when it is a single poste.

    Every filter is a set by nature, even when it resolves to one machine or
    to none: what an administrator aimed at is "the whole domain", and that is
    what the trace must say. An explicit list is a set from two distinct ids
    up — a duplicated id is still one poste, already traced by its row.

    Flat keys rather than one nested object: the console lists the details
    key by key, and ``location`` already reads as "Emplacement" there.
    """
    if target_all:
        return {"target": "all"}
    if target_domain is not None:
        return {"target": "domain", "domain": target_domain}
    if target_location is not None:
        return {"target": "location", "location": target_location}
    if target_status is not None:
        return {"target": "status", "status": target_status.value}
    distinct = len(set(machine_ids or []))
    if distinct > 1:
        return {"target": "machines", "requested": distinct}
    return None
