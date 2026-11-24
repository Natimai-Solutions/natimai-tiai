"""Windows 11 readiness: every verdict of ``readiness`` (pure), and the list's
filter and the dashboard's count reading the postes as the fiche does —
``blocked_clause`` and ``readiness`` agree, and ``win11_blocked=false`` is
their complement (requires TIAI_TEST_DATABASE_URL for the second part)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.features.asset import win11
from app.features.machine.models import Machine

SEEN = datetime(2026, 11, 20, tzinfo=UTC)

READY = {
    "os_version": "Windows 10 Pro 22H2 (Build 19045)",
    "inventory_last_seen": SEEN,
    "tpm_version": "2.0",
    "ram_total_mb": 8000,
    "system_volume_total_mb": 240_000,
    "os_architecture": "64 bits",
    "secure_boot": True,
}


@dataclass
class Case:
    hostname: str
    verdict: str | None
    fields: dict = field(default_factory=dict)
    # The memory sticks the inventory lists, in MB (None: one not read).
    modules: list[int | None] = field(default_factory=list)


CASES = [
    Case("READY", "ready"),
    Case("W11", "already", {"os_version": "Windows 11 Pro 24H2 (Build 26100)"}),
    Case("NEVER", "unknown", {"inventory_last_seen": None}),
    Case("NO-RAM", "unknown", {"ram_total_mb": None}),
    Case("NO-DISK", "unknown", {"system_volume_total_mb": None}),
    Case("SMALL-RAM", "blocked", {"ram_total_mb": 2000}),
    Case("SMALL-DISK", "blocked", {"system_volume_total_mb": 30_000}),
    Case("NO-TPM", "blocked", {"tpm_version": None}),
    Case("TPM-1.2", "blocked", {"tpm_version": "1.2"}),
    Case("SB-OFF", "check", {"secure_boot": False}),
    Case("32-BITS", "check", {"os_architecture": "32 bits"}),
    # 4 GB with a graphics chip's share kept by the firmware: Windows
    # addresses 3.4 GB; the sticks say 4 GB.
    Case("UMA-STICKS", "ready", {"ram_total_mb": 3480}, modules=[4096]),
    # Without the sticks, a little under 4 GB is to check, not refused.
    Case("UMA-NO-STICKS", "check", {"ram_total_mb": 3480}),
    Case("STICKS-2GB", "blocked", {"ram_total_mb": 8000}, modules=[2048]),
    # A stick not read: back to what Windows addresses.
    Case("STICK-UNREAD", "ready", {"ram_total_mb": 8000}, modules=[4096, None]),
    # A server never moves to Windows 11: no verdict.
    Case(
        "SERVER",
        None,
        {
            "os_version": "Windows Server 2019 Standard (Build 17763)",
            "tpm_version": None,
        },
    ),
]


def _machine(case: Case) -> Machine:
    return Machine(
        machine_uuid=case.hostname, hostname=case.hostname, **(READY | case.fields)
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.hostname)
def test_readiness(case):
    result = win11.readiness(_machine(case), win11.installed_ram_mb(case.modules))
    if case.verdict is None:
        assert result is None
    else:
        assert result is not None and result.verdict == case.verdict
        if case.verdict not in ("already", "unknown"):
            assert result.processor == "check"


def test_parts_say_why():
    result = win11.readiness(_machine(Case("X", "", {"tpm_version": "1.2"})))
    assert result is not None
    assert (result.tpm, result.ram, result.disk) == ("fail", "ok", "ok")
    result = win11.readiness(_machine(Case("X", "", {"ram_total_mb": 3480})))
    assert result is not None and result.ram == "check"


async def test_the_list_and_the_fiche_agree(client, db_session):
    from app.features.inventory.models import MemoryModule
    from tests.test_api_maintenance import _admin

    headers, _ = await _admin(client, db_session)
    for case in CASES:
        m = _machine(case)
        db_session.add(m)
        await db_session.flush()
        for i, capacity in enumerate(case.modules):
            db_session.add(
                MemoryModule(machine_id=m.id, slot=f"DIMM {i}", capacity_mb=capacity)
            )
    await db_session.commit()

    async def listed(blocked: bool) -> set[str]:
        resp = await client.get(
            "/api/v1/machines",
            headers=headers,
            params={"win11_blocked": str(blocked).lower(), "page_size": 200},
        )
        assert resp.status_code == 200, resp.text
        return {m["hostname"] for m in resp.json()["items"]}

    blocked = await listed(True)
    assert blocked == {c.hostname for c in CASES if c.verdict == "blocked"}
    # The complement: every other poste, those with a part unread included.
    assert await listed(False) == {c.hostname for c in CASES} - blocked

    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.json()["machines_win11_blocked"] == len(blocked)

    # And the fiche says the same, the sticks read from the inventory.
    resp = await client.get(
        "/api/v1/machines", headers=headers, params={"page_size": 200}
    )
    ids = {m["hostname"]: m["id"] for m in resp.json()["items"]}
    for case in CASES:
        detail = (
            await client.get(f"/api/v1/machines/{ids[case.hostname]}", headers=headers)
        ).json()
        verdict = detail["windows11"]["verdict"] if detail["windows11"] else None
        assert verdict == case.verdict, case.hostname
