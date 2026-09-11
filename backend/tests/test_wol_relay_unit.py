"""Relaying a wake: the eligibility rules (no database, no socket).

Who may put the magic packet on the wire for a poste that is off is the
whole feature — a relay on the wrong site broadcasts into the void and the
console still reports success — so the rules are pure functions, tested here.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.features.machine.models import Machine
from app.features.wol.relay import may_claim, same_subnet, shares_wire


def machine(**kwargs) -> Machine:
    return Machine(id=uuid.uuid4(), machine_uuid=str(uuid.uuid4()), **kwargs)


def test_location_decides_when_the_target_has_one():
    """A domain spans every site of an académie; a site name does not."""
    target = machine(location="Lycée de Taravao", domain="natimai.local")
    assert shares_wire(machine(location="Lycée de Taravao", domain="other"), target)
    assert not shares_wire(
        machine(location="Collège de Papeete", domain="natimai.local"), target
    )
    # A relay that names no site is not on the target's — it is unknown, and
    # unknown does not get to broadcast on the target's behalf.
    assert not shares_wire(machine(location=None, domain="natimai.local"), target)


def test_domain_is_the_fallback_for_a_target_without_a_location():
    target = machine(location=None, domain="natimai.local")
    assert shares_wire(
        machine(location="Lycée de Taravao", domain="natimai.local"), target
    )
    assert not shares_wire(machine(domain="other.local"), target)
    assert not shares_wire(machine(domain=None), target)


def test_a_target_with_neither_has_no_peer():
    assert not shares_wire(machine(domain="natimai.local"), machine())


def test_a_poste_never_relays_for_itself():
    target = machine(location="Lycée de Taravao")
    assert not shares_wire(target, target)


@pytest.mark.parametrize(
    ("relay", "target", "expected"),
    [
        (("10.4.7.9", 16), ("10.4.200.1", 16), True),
        (("10.4.7.9", 24), ("10.4.7.200", 24), True),
        (("10.4.7.9", 24), ("10.4.8.1", 24), False),
        # Unknown is not "same": a missing mask waits the grace like another VLAN.
        (("10.4.7.9", None), ("10.4.7.200", 24), False),
        ((None, 24), ("10.4.7.200", 24), False),
        (("2001:db8::1", 64), ("2001:db8::2", 64), False),
    ],
)
def test_same_subnet(relay, target, expected):
    a = machine(ip_address=relay[0], ip_prefix_length=relay[1])
    b = machine(ip_address=target[0], ip_prefix_length=target[1])
    assert same_subnet(a, b) is expected


def test_the_same_subnet_claims_at_once_and_the_rest_of_the_site_waits(monkeypatch):
    """The poste whose broadcast is certain to reach the target goes first."""
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 90)
    queued = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    target = machine(
        location="Lycée de Taravao", ip_address="10.4.7.200", ip_prefix_length=24
    )
    near = machine(
        location="Lycée de Taravao", ip_address="10.4.7.9", ip_prefix_length=24
    )
    far = machine(
        location="Lycée de Taravao", ip_address="10.4.8.9", ip_prefix_length=24
    )
    elsewhere = machine(
        location="Collège de Papeete", ip_address="10.4.7.10", ip_prefix_length=24
    )

    assert may_claim(near, target, queued_at=queued, now=queued)
    assert not may_claim(far, target, queued_at=queued, now=queued)
    assert may_claim(far, target, queued_at=queued, now=queued + timedelta(seconds=90))
    # Another site never, however long the wake has waited: its broadcast
    # reaches its own wire and nothing else.
    assert not may_claim(
        elsewhere, target, queued_at=queued, now=queued + timedelta(hours=1)
    )


def test_a_zero_grace_removes_the_preference(monkeypatch):
    monkeypatch.setattr(settings, "WOL_RELAY_SUBNET_GRACE_SECONDS", 0)
    queued = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    target = machine(
        location="Lycée de Taravao", ip_address="10.4.7.200", ip_prefix_length=24
    )
    far = machine(
        location="Lycée de Taravao", ip_address="10.4.8.9", ip_prefix_length=24
    )
    assert may_claim(far, target, queued_at=queued, now=queued)
