"""Per-account e-mail cadences: who is mailed, when, and what is in it.

DB-backed (require TIAI_TEST_DATABASE_URL) except the rendering tests, which are
pure functions over a dataclass.

Mailgun is never reached: the notification code queues rows in the e-mail
outbox (sent later by the worker, exercised in ``test_outbox``), and those rows
are what the assertions here read.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings


@pytest.fixture
def mailgun_configured(monkeypatch):
    """Nothing is queued while Mailgun is off — delivery tests turn it on."""
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test.local")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")


async def _queued(db_session) -> list:
    """The outbox rows, ordered by address — what would go out, and to whom."""
    from sqlmodel import col, select

    from app.features.notification.models import EmailOutbox

    result = await db_session.exec(
        select(EmailOutbox).order_by(col(EmailOutbox.to_address))
    )
    return result.all()


async def _recipients(db_session) -> list[str]:
    return [row.to_address for row in await _queued(db_session)]


async def _user(db_session, email: str, preference: str, *, is_active: bool = True):
    from app.features.user import crud
    from app.features.user.models import Role

    user = await crud.create_user(
        db_session, email=email, password="pw-not-used-here", role=Role.READONLY
    )
    user.email_preference = preference
    user.is_active = is_active
    db_session.add(user)
    await db_session.commit()
    return user


# --- recipients -------------------------------------------------------------


async def test_recipients_selects_only_the_asked_cadence(db_session):
    from app.features.notification.recipients import recipients_for
    from app.features.user.models import EmailPreference

    await _user(db_session, "daily@test.local", "digest_daily")
    await _user(db_session, "events@test.local", "digest_events")
    await _user(db_session, "now@test.local", "immediate")
    await _user(db_session, "quiet@test.local", "none")

    daily = await recipients_for(db_session, [EmailPreference.DIGEST_DAILY])
    assert daily == ["daily@test.local"]

    immediate = await recipients_for(db_session, [EmailPreference.IMMEDIATE])
    assert immediate == ["now@test.local"]

    both = await recipients_for(
        db_session, [EmailPreference.DIGEST_DAILY, EmailPreference.DIGEST_EVENTS]
    )
    assert both == ["daily@test.local", "events@test.local"]


async def test_recipients_excludes_deactivated_accounts(db_session):
    from app.features.notification.recipients import recipients_for
    from app.features.user.models import EmailPreference

    await _user(db_session, "gone@test.local", "digest_daily", is_active=False)

    assert await recipients_for(db_session, [EmailPreference.DIGEST_DAILY]) == []


# --- digest content ---------------------------------------------------------


def _digest(**overrides):
    from app.features.notification.digest import Digest

    base = {
        "generated_at": datetime(2026, 8, 20, 18, 0, tzinfo=UTC),
        "total": 10,
        "online": 9,
        "with_active_threats": 0,
        "with_high_severity_updates": 0,
        "needs_verification": 0,
        "new_threats_24h": 0,
        "outdated_antivirus": 0,
        "wu_pending": 0,
        "reboot_required": 0,
        "inactive": 0,
    }
    base.update(overrides)
    return Digest(**base)


@pytest.mark.parametrize(
    "field",
    [
        "with_active_threats",
        "with_high_severity_updates",
        "needs_verification",
        "new_threats_24h",
    ],
)
def test_each_event_field_makes_a_day_reportable(field):
    assert _digest(**{field: 1}).has_events is True


@pytest.mark.parametrize(
    "field", ["outdated_antivirus", "wu_pending", "reboot_required", "inactive"]
)
def test_running_state_alone_is_not_an_event(field):
    """Otherwise the "only if something happened" cadence fires every morning.

    A parc with one permanently périmé antivirus would send an event digest
    every day, which is the *other* cadence — and the distinction between the
    two settings would exist only in the account page.
    """
    assert _digest(**{field: 7}).has_events is False


def test_quiet_digest_says_so_in_the_subject():
    from app.features.notification.digest import render_digest

    subject, body = render_digest(_digest())
    assert "rien à signaler" in subject
    assert "Aucune menace active" in body


def test_digest_subject_leads_with_the_worst_news():
    from app.features.notification.digest import render_digest

    subject, _ = render_digest(
        _digest(with_active_threats=3, with_high_severity_updates=12)
    )
    assert "3 poste(s) avec menace active" in subject


def test_digest_states_the_overflow_rather_than_cutting_it():
    from app.features.notification.digest import MachineLine, render_digest

    lines = [
        MachineLine(hostname=f"PC-{i}", detail="1 menace(s) active(s)")
        for i in range(3)
    ]
    _, body = render_digest(_digest(with_active_threats=25, threat_lines=lines))

    assert "PC-0" in body
    assert "… et 22 autre(s) poste(s)" in body


# --- digest delivery --------------------------------------------------------


async def test_daily_digest_goes_only_to_daily_when_nothing_happened(
    db_session, mailgun_configured
):
    from app.features.notification import digest

    await _user(db_session, "daily@test.local", "digest_daily")
    await _user(db_session, "events@test.local", "digest_events")
    await _user(db_session, "quiet@test.local", "none")

    queued = await digest.send_daily_digest(db_session)

    assert queued == 1
    assert await _recipients(db_session) == ["daily@test.local"]


async def test_event_digest_joins_in_on_a_day_with_a_threat(
    db_session, mailgun_configured
):
    from app.features.machine.models import Machine
    from app.features.notification import digest
    from app.features.threat.models import Threat

    await _user(db_session, "daily@test.local", "digest_daily")
    await _user(db_session, "events@test.local", "digest_events")

    machine = Machine(machine_uuid="digest-threat")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    db_session.add(Threat(machine_id=machine.id, detection_id="d-1", status="active"))
    await db_session.commit()

    queued = await digest.send_daily_digest(db_session)

    assert queued == 2
    assert await _recipients(db_session) == ["daily@test.local", "events@test.local"]


async def test_digest_is_addressed_one_recipient_at_a_time(
    db_session, mailgun_configured
):
    """Never a shared To:, which would hand every operator the user list."""
    from app.features.notification import digest

    await _user(db_session, "a@test.local", "digest_daily")
    await _user(db_session, "b@test.local", "digest_daily")

    await digest.send_daily_digest(db_session)

    assert [row.to_address for row in await _queued(db_session)] == [
        "a@test.local",
        "b@test.local",
    ]


async def test_a_console_with_no_account_mails_nobody(db_session, mailgun_configured):
    """No account, no recipient — and no configured address to substitute.

    A console in this state is one nobody can log into; the seeded first admin
    (``scripts/seed_admin``) is what keeps a real deployment watched, on the
    daily digest its default gives it.
    """
    from app.features.notification import digest

    assert await digest.send_daily_digest(db_session) == 0
    assert await _queued(db_session) == []


async def test_opting_everyone_out_really_stops_the_mail(
    db_session, mailgun_configured
):
    """« Aucun e-mail » is final: nothing anywhere can undo the choice.

    A team that has every account on « aucun e-mail » (or on the immediate
    alerts alone) has answered the question, and no setting outside the console
    may keep mailing them a digest they turned off.
    """
    from app.features.notification import digest

    await _user(db_session, "quiet@test.local", "none")
    await _user(db_session, "also-quiet@test.local", "immediate")

    assert await digest.send_daily_digest(db_session) == 0
    assert await _queued(db_session) == []


async def test_a_quiet_day_simply_sends_nothing(db_session, mailgun_configured):
    """An events-only account on a calm day hears nothing — as it asked."""
    from app.features.notification import digest

    await _user(db_session, "events@test.local", "digest_events")

    assert await digest.send_daily_digest(db_session) == 0
    assert await _queued(db_session) == []


async def test_digest_counts_the_fleet_it_reads(db_session, monkeypatch):
    from app.features.machine.models import Machine
    from app.features.notification import digest
    from app.features.windows_update.models import WindowsUpdate

    machine = Machine(machine_uuid="digest-wu", hostname="PC-WU", wu_pending_count=2)
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    db_session.add(
        WindowsUpdate(
            machine_id=machine.id,
            update_id="u-1",
            title="Mise à jour cumulative",
            severity="critical",
            type="software",
        )
    )
    await db_session.commit()

    built = await digest.build_digest(db_session)

    assert built.with_high_severity_updates == 1
    assert built.wu_pending == 1
    assert built.has_events is True
    _, body = digest.render_digest(built)
    assert "PC-WU" in body


# --- immediate threat alerts ------------------------------------------------


def _detection(detected_at, detection_id="d-1"):
    from app.features.threat.crud import NewDetection

    return NewDetection(
        detection_id=detection_id,
        threat_name="Trojan:Win32/Test",
        severity="high",
        status="active",
        detected_at=detected_at,
    )


def test_backfilled_history_is_not_alerted_on():
    """A poste enrolling hands over years of Defender history in one call."""
    from app.features.notification.threat_alert import recent_detections

    old = _detection(datetime.now(UTC) - timedelta(days=400), "old")
    fresh = _detection(datetime.now(UTC) - timedelta(minutes=5), "fresh")

    kept = recent_detections([old, fresh])

    assert [d.detection_id for d in kept] == ["fresh"]


def test_a_detection_without_a_date_is_still_alerted_on():
    """Unknown is not old: Defender did not say when, the agent says now."""
    from app.features.notification.threat_alert import recent_detections

    assert len(recent_detections([_detection(None)])) == 1


def test_alert_names_the_poste_and_the_threat():
    from app.features.machine.models import Machine
    from app.features.notification.threat_alert import MachineContext, render_alert

    machine = Machine(machine_uuid="uuid-1", hostname="PC-042", ip_address="10.0.0.4")
    subject, body = render_alert(
        MachineContext.of(machine), [_detection(datetime.now(UTC))]
    )

    assert "PC-042" in subject
    assert "Trojan:Win32/Test" in body
    assert "10.0.0.4" in body


async def test_immediate_alert_goes_only_to_the_immediate_cadence(
    db_session, mailgun_configured
):
    from app.features.machine.models import Machine
    from app.features.notification import threat_alert

    await _user(db_session, "now@test.local", "immediate")
    await _user(db_session, "daily@test.local", "digest_daily")

    context = threat_alert.MachineContext.of(
        Machine(machine_uuid="uuid-2", hostname="PC-7")
    )
    queued = await threat_alert.queue_threat_alert(
        db_session, context, [_detection(datetime.now(UTC))]
    )
    await db_session.commit()

    assert queued == 1
    assert await _recipients(db_session) == ["now@test.local"]


async def test_no_alert_when_every_detection_is_old(db_session, mailgun_configured):
    from app.features.machine.models import Machine
    from app.features.notification import threat_alert

    await _user(db_session, "now@test.local", "immediate")

    context = threat_alert.MachineContext.of(Machine(machine_uuid="uuid-3"))
    queued = await threat_alert.queue_threat_alert(
        db_session, context, [_detection(datetime.now(UTC) - timedelta(days=30))]
    )
    await db_session.commit()

    assert queued == 0
    assert await _queued(db_session) == []


def test_a_long_alert_is_capped_like_the_digest():
    """One poste's whole undated history must not become a 300-line mail."""
    from app.features.machine.models import Machine
    from app.features.notification.threat_alert import MachineContext, render_alert

    detections = [_detection(None, f"d-{i}") for i in range(50)]
    subject, body = render_alert(
        MachineContext.of(Machine(machine_uuid="uuid-many")), detections
    )

    bullets = [line for line in body.splitlines() if line.startswith("  •")]
    assert len(bullets) == settings.NOTIFICATION_MAX_ITEMS
    assert f"… et {50 - settings.NOTIFICATION_MAX_ITEMS} autre(s) détection(s)" in body
    # The count is still the truth, in the subject and the opening line.
    assert "50 menaces" in subject


def test_the_digest_hour_must_be_a_real_hour():
    """Out of range, the daily job would never come due and fail silently."""
    import pydantic
    import pytest as pytest_module

    from app.core.config import Settings

    with pytest_module.raises(pydantic.ValidationError):
        Settings(DIGEST_HOUR_UTC=25)
