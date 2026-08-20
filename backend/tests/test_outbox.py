"""The e-mail outbox: queued in the caller's transaction, drained with retries.

DB-backed (require TIAI_TEST_DATABASE_URL) except the backoff arithmetic.
Mailgun is never reached: the drain tests monkeypatch ``send_email`` where the
outbox module imported it.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings


@pytest.fixture
def mailgun_configured(monkeypatch):
    """queue_email refuses to queue when Mailgun is off — most tests want it on."""
    monkeypatch.setattr(settings, "MAILGUN_DOMAIN", "mg.test.local")
    monkeypatch.setattr(settings, "MAILGUN_API_KEY", "key-test")


class _Mailgun:
    """Stand-in for the Mailgun client, scripted to fail for chosen addresses."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.failing: set[str] = set()

    async def __call__(self, subject: str, text: str, to: list[str] | None = None):
        if to and to[0] in self.failing:
            raise RuntimeError("mailgun said no")
        self.sent.append({"subject": subject, "text": text, "to": to})
        return True


async def _rows(db_session):
    from sqlmodel import col, select

    from app.features.notification.models import EmailOutbox

    result = await db_session.exec(
        select(EmailOutbox).order_by(col(EmailOutbox.to_address))
    )
    return result.all()


# --- queueing ---------------------------------------------------------------


async def test_a_queued_mail_lives_and_dies_with_the_callers_transaction(
    db_session, mailgun_configured
):
    from app.features.notification.outbox import queue_email

    assert queue_email(db_session, to="a@test.local", subject="s", text="t") is True
    await db_session.rollback()
    assert await _rows(db_session) == []

    assert queue_email(db_session, to="a@test.local", subject="s", text="t") is True
    await db_session.commit()

    (row,) = await _rows(db_session)
    assert (row.to_address, row.status, row.attempts) == ("a@test.local", "pending", 0)


async def test_nothing_is_queued_when_mailgun_is_not_configured(db_session):
    """Parity with the old direct send: no configuration, no mail — and no
    backlog of rows nothing will ever be able to send."""
    from app.features.notification.outbox import queue_email

    assert queue_email(db_session, to="a@test.local", subject="s", text="t") is False
    await db_session.commit()
    assert await _rows(db_session) == []


# --- draining ---------------------------------------------------------------


async def test_drain_sends_the_due_mail_and_marks_it_sent(
    db_session, mailgun_configured, monkeypatch
):
    from app.features.notification import outbox

    outbox.queue_email(db_session, to="a@test.local", subject="Sujet A", text="corps")
    outbox.queue_email(db_session, to="b@test.local", subject="Sujet B", text="corps")
    await db_session.commit()

    mailgun = _Mailgun()
    monkeypatch.setattr(outbox, "send_email", mailgun)

    assert await outbox.send_pending(db_session) == 2

    rows = await _rows(db_session)
    assert [(r.status, r.to_address) for r in rows] == [
        ("sent", "a@test.local"),
        ("sent", "b@test.local"),
    ]
    assert all(r.sent_at is not None for r in rows)
    assert [call["to"] for call in mailgun.sent] == [["a@test.local"], ["b@test.local"]]


async def test_a_mail_not_yet_due_waits_its_turn(
    db_session, mailgun_configured, monkeypatch
):
    from app.features.notification import outbox
    from app.features.notification.models import EmailOutbox

    db_session.add(
        EmailOutbox(
            to_address="later@test.local",
            subject="s",
            body="t",
            next_attempt_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db_session.commit()

    mailgun = _Mailgun()
    monkeypatch.setattr(outbox, "send_email", mailgun)

    assert await outbox.send_pending(db_session) == 0
    assert mailgun.sent == []


async def test_a_failure_backs_off_instead_of_losing_the_mail(
    db_session, mailgun_configured, monkeypatch
):
    from app.features.notification import outbox

    outbox.queue_email(db_session, to="down@test.local", subject="s", text="t")
    outbox.queue_email(db_session, to="fine@test.local", subject="s", text="t")
    await db_session.commit()

    mailgun = _Mailgun()
    mailgun.failing = {"down@test.local"}
    monkeypatch.setattr(outbox, "send_email", mailgun)

    # One address failing does not cost the other its mail.
    assert await outbox.send_pending(db_session) == 1

    failed, sent = await _rows(db_session)
    assert (sent.to_address, sent.status) == ("fine@test.local", "sent")
    assert (failed.status, failed.attempts) == ("pending", 1)
    assert "mailgun said no" in (failed.last_error or "")
    assert failed.next_attempt_at > datetime.now(UTC)

    # Not due again yet: an immediate re-drain must not hammer Mailgun.
    assert await outbox.send_pending(db_session) == 0


def test_the_backoff_doubles_from_a_minute_and_caps_at_an_hour():
    from app.features.notification.outbox import _retry_delay

    assert _retry_delay(1) == timedelta(seconds=60)
    assert _retry_delay(2) == timedelta(seconds=120)
    assert _retry_delay(5) == timedelta(seconds=960)
    assert _retry_delay(12) == timedelta(hours=1)


async def test_a_mail_is_abandoned_after_the_last_attempt(
    db_session, mailgun_configured, monkeypatch
):
    from app.features.notification import outbox
    from app.features.notification.models import EmailOutbox

    db_session.add(
        EmailOutbox(
            to_address="dead@test.local",
            subject="s",
            body="t",
            attempts=settings.EMAIL_MAX_ATTEMPTS - 1,
        )
    )
    await db_session.commit()

    mailgun = _Mailgun()
    mailgun.failing = {"dead@test.local"}
    monkeypatch.setattr(outbox, "send_email", mailgun)

    assert await outbox.send_pending(db_session) == 0

    (row,) = await _rows(db_session)
    assert row.status == "abandoned"
    assert row.attempts == settings.EMAIL_MAX_ATTEMPTS
    assert "mailgun said no" in (row.last_error or "")

    # Abandoned means abandoned: no further drain ever touches it.
    mailgun.failing = set()
    assert await outbox.send_pending(db_session) == 0
    assert mailgun.sent == []


# --- purge ------------------------------------------------------------------


async def test_purge_drops_only_old_settled_rows(db_session):
    from app.features.notification import outbox
    from app.features.notification.models import EmailOutbox, EmailStatus

    old = datetime.now(UTC) - timedelta(days=settings.EMAIL_OUTBOX_RETENTION_DAYS + 1)
    for to, status, created_at in [
        ("old-sent@test.local", EmailStatus.SENT, old),
        ("old-abandoned@test.local", EmailStatus.ABANDONED, old),
        # A pending row is a mail still owed, whatever its age.
        ("old-pending@test.local", EmailStatus.PENDING, old),
        ("recent-sent@test.local", EmailStatus.SENT, datetime.now(UTC)),
    ]:
        db_session.add(
            EmailOutbox(
                to_address=to,
                subject="s",
                body="t",
                status=status,
                created_at=created_at,
            )
        )
    await db_session.commit()

    assert await outbox.purge_settled(db_session) == 2

    remaining = {row.to_address for row in await _rows(db_session)}
    assert remaining == {"old-pending@test.local", "recent-sent@test.local"}
