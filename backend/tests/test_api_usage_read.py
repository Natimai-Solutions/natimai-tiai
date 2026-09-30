"""Reading the usage counters (require TIAI_TEST_DATABASE_URL): the list's
column, filter and sort, the export, the dashboard, the fiche and the settings.

Counters are written straight into the table, relative to the real clock's
current hour: the reads compute their window from ``utcnow()``, and a bucket
an hour or a day back is inside it whatever the minute the test runs at.
"""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from openpyxl import load_workbook

from app.api.csv_export import DELIMITER
from tests.test_api_maintenance import _admin, _tech

H = 3600


def _this_hour() -> datetime:
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


async def _poste(db_session, hostname, *, hours=0.0, enrolled_days_ago=30, spread=1):
    """A poste known for ``enrolled_days_ago`` days, on for ``hours`` hours
    over the last day — ``spread`` buckets, so a poste has several rows."""
    from app.features.machine.models import Machine
    from app.features.usage.models import MachineUptime

    machine = Machine(
        machine_uuid=str(uuid.uuid4()),
        hostname=hostname,
        first_seen=datetime.now(UTC) - timedelta(days=enrolled_days_ago),
    )
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    # Read once: a later commit expires the instance, and an async session
    # cannot lazy-load it back.
    machine_id = machine.id
    seconds = round(hours * H)
    if seconds:
        # Whole hours first, going back from an hour ago, then the rest.
        hour = _this_hour() - timedelta(hours=1)
        buckets = []
        while seconds > 0:
            buckets.append(min(H, seconds))
            seconds -= buckets[-1]
        for i, value in enumerate(buckets):
            db_session.add(
                MachineUptime(
                    machine_id=machine_id,
                    hour=hour - timedelta(hours=i * spread),
                    seconds_on=value,
                )
            )
        await db_session.commit()
    return str(machine_id)


async def _add_hour(db_session, machine_id, hour, seconds):
    from app.features.usage.models import MachineUptime

    db_session.add(
        MachineUptime(machine_id=uuid.UUID(machine_id), hour=hour, seconds_on=seconds)
    )
    await db_session.commit()


async def _list(client, headers, **params):
    resp = await client.get("/api/v1/machines", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_host(body) -> dict[str, float | None]:
    return {m["hostname"]: m["usage_hours"] for m in body["items"]}


async def _fleet(db_session):
    """Four postes around the default thresholds (10 h, 30 h), plus one
    enrolled yesterday and one never seen on."""
    return {
        "idle": await _poste(db_session, "IDLE"),
        "light": await _poste(db_session, "LIGHT", hours=4.5),
        "mid": await _poste(db_session, "MID", hours=12.25),
        "busy": await _poste(db_session, "BUSY", hours=31),
        "new": await _poste(db_session, "NEW", hours=2, enrolled_days_ago=1),
    }


# --- The list ---------------------------------------------------------------


async def test_rows_carry_their_hours_and_the_window(client, db_session):
    admin, _ = await _admin(client, db_session)
    await _fleet(db_session)

    body = await _list(client, admin)
    assert body["usage_days"] == 7
    # The thresholds ride along, for the list's own filter.
    assert (body["usage_low_hours"], body["usage_high_hours"]) == (10, 30)
    assert _by_host(body) == {
        "IDLE": 0.0,
        "LIGHT": 4.5,
        "MID": 12.2,
        "BUSY": 31.0,
        # Enrolled inside the window: not zero, not a figure — unknown.
        "NEW": None,
    }


async def test_low_filter_keeps_the_idle_and_leaves_out_the_newcomer(
    client, db_session
):
    admin, _ = await _admin(client, db_session)
    await _fleet(db_session)

    body = await _list(client, admin, usage_hours_below=10)
    assert set(_by_host(body)) == {"IDLE", "LIGHT"}
    assert body["total"] == 2


async def test_high_filter_and_combined_bounds(client, db_session):
    admin, _ = await _admin(client, db_session)
    await _fleet(db_session)

    assert set(_by_host(await _list(client, admin, usage_hours_above=30))) == {"BUSY"}
    between = await _list(client, admin, usage_hours_above=4, usage_hours_below=30)
    assert set(_by_host(between)) == {"LIGHT", "MID"}
    # The upper bound has no reason to leave out a newcomer.
    assert "NEW" in _by_host(await _list(client, admin, usage_hours_above=1))


async def test_the_window_can_be_widened_per_request(client, db_session):
    admin, _ = await _admin(client, db_session)
    old = await _poste(db_session, "OLD")
    await _add_hour(db_session, old, _this_hour() - timedelta(days=10), 1800)

    assert _by_host(await _list(client, admin))["OLD"] == 0.0
    wide = await _list(client, admin, usage_days=14)
    assert wide["usage_days"] == 14
    assert _by_host(wide)["OLD"] == 0.5
    bad = await client.get("/api/v1/machines", headers=admin, params={"usage_days": 91})
    assert bad.status_code == 422


async def test_the_list_window_follows_the_console_setting(client, db_session):
    from app.features.setting import crud

    admin, _ = await _admin(client, db_session)
    await crud.set_value(db_session, crud.KEY_USAGE_WINDOW, 2, actor="t")
    await db_session.commit()
    assert (await _list(client, admin))["usage_days"] == 2


async def test_sort_puts_zeros_together_and_newcomers_last(client, db_session):
    admin, _ = await _admin(client, db_session)
    await _fleet(db_session)
    await _poste(db_session, "IDLE-2")

    asc = await _list(client, admin, sort_by="usage_hours", sort_desc=False)
    hosts = [m["hostname"] for m in asc["items"]]
    assert set(hosts[:2]) == {"IDLE", "IDLE-2"}
    assert hosts[2:] == ["LIGHT", "MID", "BUSY", "NEW"]
    desc = await _list(client, admin, sort_by="usage_hours", sort_desc=True)
    assert [m["hostname"] for m in desc["items"]][:3] == ["BUSY", "MID", "LIGHT"]
    assert desc["items"][-1]["hostname"] == "NEW"


async def test_the_join_does_not_inflate_the_page_count(client, db_session):
    admin, _ = await _admin(client, db_session)
    # Thirty-one rows for one poste, spread over the window.
    await _poste(db_session, "SPREAD", hours=31, spread=3)
    await _poste(db_session, "OTHER")

    body = await _list(client, admin, page_size=1)
    assert body["total"] == 2
    assert _by_host(await _list(client, admin))["SPREAD"] == 31.0


# --- Export -----------------------------------------------------------------


async def test_export_names_its_window_and_writes_numbers(client, db_session):
    admin, _ = await _admin(client, db_session)
    await _fleet(db_session)
    params = {"columns": "hostname,usage_hours", "usage_hours_below": 10}

    resp = await client.get("/api/v1/machines/export.csv", headers=admin, params=params)
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=DELIMITER))
    assert rows[0] == ["Nom", "Heures allumées (7 j)"]
    assert sorted(rows[1:]) == [["IDLE", "0.0"], ["LIGHT", "4.5"]]

    resp = await client.get(
        "/api/v1/machines/export.xlsx",
        headers=admin,
        params={"columns": "hostname,usage_hours", "usage_days": 3},
    )
    sheet = load_workbook(io.BytesIO(resp.content))["Parc"]
    assert sheet.cell(1, 2).value == "Heures allumées (3 j)"
    cells = {
        sheet.cell(r, 1).value: sheet.cell(r, 2).value
        for r in range(2, sheet.max_row + 1)
    }
    # A number Excel can sum, not text; whole values read back as integers.
    assert cells["MID"] == 12.2
    assert cells["BUSY"] == 31
    assert cells["NEW"] is None


# --- Dashboard --------------------------------------------------------------


async def test_overview_counts_and_serves_its_thresholds(client, db_session):
    admin, _ = await _admin(client, db_session)
    empty = (await client.get("/api/v1/stats/overview", headers=admin)).json()
    assert empty["usage_since"] is None
    assert (empty["machines_usage_low"], empty["machines_usage_high"]) == (0, 0)

    await _fleet(db_session)
    stats = (await client.get("/api/v1/stats/overview", headers=admin)).json()
    assert stats["machines_usage_low"] == 2  # IDLE, LIGHT — not NEW
    assert stats["machines_usage_high"] == 1  # BUSY
    assert (
        stats["usage_low_hours"],
        stats["usage_high_hours"],
        stats["usage_window_days"],
    ) == (10, 30, 7)
    assert stats["usage_since"] is not None

    # The card and the list it opens agree.
    body = await _list(client, admin, usage_hours_below=stats["usage_low_hours"])
    assert body["total"] == stats["machines_usage_low"]


async def test_a_new_threshold_counts_at_once(client, db_session):
    admin, _ = await _admin(client, db_session)
    await _fleet(db_session)

    resp = await client.patch(
        "/api/v1/settings", headers=admin, json={"usage_low_hours": 20}
    )
    assert resp.status_code == 200, resp.text
    stats = (await client.get("/api/v1/stats/overview", headers=admin)).json()
    assert stats["usage_low_hours"] == 20
    assert stats["machines_usage_low"] == 3  # IDLE, LIGHT, MID


# --- The fiche --------------------------------------------------------------


async def test_detail_carries_the_console_window(client, db_session):
    admin, _ = await _admin(client, db_session)
    busy = await _poste(db_session, "BUSY", hours=31)

    detail = (await client.get(f"/api/v1/machines/{busy}", headers=admin)).json()
    assert (detail["usage_hours"], detail["usage_days"]) == (31.0, 7)


async def test_days_are_cut_in_the_readers_zone(client, db_session):
    admin, _ = await _admin(client, db_session)
    poste = await _poste(db_session, "PC")
    utc_day = datetime.now(UTC).date() - timedelta(days=2)
    # 09:00 UTC is 23:00 the evening before in Tahiti (UTC−10).
    await _add_hour(
        db_session,
        poste,
        datetime(utc_day.year, utc_day.month, utc_day.day, 9, tzinfo=UTC),
        3600,
    )

    def hours_on(body):
        return {d["date"]: d["hours"] for d in body["daily"]}

    tahiti = (
        await client.get(
            f"/api/v1/machines/{poste}/usage",
            headers=admin,
            params={"tz": "Pacific/Tahiti", "days": 5},
        )
    ).json()
    assert tahiti["tz"] == "Pacific/Tahiti"
    assert len(tahiti["daily"]) == 5
    assert hours_on(tahiti)[str(utc_day - timedelta(days=1))] == 1.0
    assert hours_on(tahiti)[str(utc_day)] == 0.0
    assert tahiti["total_hours"] == 1.0

    utc = (
        await client.get(
            f"/api/v1/machines/{poste}/usage", headers=admin, params={"days": 5}
        )
    ).json()
    assert utc["tz"] == "UTC"
    assert hours_on(utc)[str(utc_day)] == 1.0
    # Oldest first, today last.
    assert utc["daily"][-1]["date"] == str(datetime.now(UTC).date())


async def test_fiche_usage_defaults_and_refusals(client, db_session):
    admin, _ = await _admin(client, db_session)
    poste = await _poste(db_session, "PC")

    body = (
        await client.get(
            f"/api/v1/machines/{poste}/usage",
            headers=admin,
            params={"tz": "Nowhere/Atlantis"},
        )
    ).json()
    assert (body["days"], body["tz"], body["total_hours"]) == (28, "UTC", 0.0)
    assert body["usage_since"] is None
    missing = await client.get(f"/api/v1/machines/{uuid.uuid4()}/usage", headers=admin)
    assert missing.status_code == 404
    too_long = await client.get(
        f"/api/v1/machines/{poste}/usage", headers=admin, params={"days": 91}
    )
    assert too_long.status_code == 422


# --- Settings ---------------------------------------------------------------


async def test_settings_show_usage_and_where_it_comes_from(client, db_session):
    admin, _ = await _admin(client, db_session)
    got = (await client.get("/api/v1/settings", headers=admin)).json()
    assert (
        got["usage_window_days"],
        got["usage_low_hours"],
        got["usage_high_hours"],
    ) == (7, 10, 30)
    assert (
        got["env_usage_window_days"],
        got["env_usage_low_hours"],
        got["env_usage_high_hours"],
    ) == (7, 10, 30)
    groups = {g["label"]: {i["key"] for i in g["items"]} for g in got["environment"]}
    assert groups["Utilisation des postes"] == {
        "USAGE_WINDOW_DAYS",
        "USAGE_LOW_HOURS",
        "USAGE_HIGH_HOURS",
        "USAGE_RETENTION_DAYS",
    }


async def test_thresholds_must_hold_together(client, db_session):
    admin, _ = await _admin(client, db_session)

    async def patch(body):
        return await client.patch("/api/v1/settings", headers=admin, json=body)

    assert (
        await patch({"usage_low_hours": 30, "usage_high_hours": 30})
    ).status_code == 422
    # One threshold alone is checked against the stored other one.
    refused = await patch({"usage_low_hours": 40})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "request.validation_error"
    # Unreachable: 200 h in a week of 168.
    assert (await patch({"usage_high_hours": 200})).status_code == 422
    # ... but reachable once the window is widened in the same patch.
    ok = await patch({"usage_high_hours": 200, "usage_window_days": 14})
    assert ok.status_code == 200, ok.text
    assert (ok.json()["usage_high_hours"], ok.json()["usage_window_days"]) == (200, 14)
    # Narrowing the window under a stored threshold is refused too.
    assert (await patch({"usage_window_days": 7})).status_code == 422
    # A refused patch writes nothing.
    got = (await client.get("/api/v1/settings", headers=admin)).json()
    assert (got["usage_low_hours"], got["usage_window_days"]) == (10, 14)


async def test_null_hands_a_setting_back_to_the_environment(client, db_session):
    admin, _ = await _admin(client, db_session)
    await client.patch("/api/v1/settings", headers=admin, json={"usage_low_hours": 5})
    resp = await client.patch(
        "/api/v1/settings", headers=admin, json={"usage_low_hours": None}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["usage_low_hours"] == 10


async def test_changing_usage_settings_needs_the_write_permission(client, db_session):
    tech, _ = await _tech(client, db_session)
    resp = await client.patch(
        "/api/v1/settings", headers=tech, json={"usage_low_hours": 5}
    )
    assert resp.status_code == 403
    # Reading the counts does not: the dashboard serves the thresholds.
    stats = await client.get("/api/v1/stats/overview", headers=tech)
    assert stats.status_code == 200
    assert stats.json()["usage_low_hours"] == 10
