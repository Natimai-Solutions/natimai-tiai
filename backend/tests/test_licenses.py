"""Software licences (C6): the count against the installed programs, the
verdicts, the rights, the scope, the list's filter, the digest."""

from datetime import date, timedelta

from tests.scope_helpers import account, group, two_sites

API = "/api/v1/licenses"


async def _install(db_session, machine_id, name, version="1.0", publisher=""):
    """Put a program on a poste, through the catalogue."""
    from sqlmodel import select

    from app.features.inventory.models import MachineSoftware, Software

    found = await db_session.exec(
        select(Software).where(
            Software.name == name,
            Software.version == version,
            Software.publisher == publisher,
        )
    )
    soft = found.first()
    if soft is None:
        soft = Software(name=name, version=version, publisher=publisher)
        db_session.add(soft)
        await db_session.commit()
        await db_session.refresh(soft)
    db_session.add(MachineSoftware(machine_id=machine_id, software_id=soft.id))
    await db_session.commit()


async def _create(client, headers, **fields):
    body = {"name": "Office 2021", "patterns": ["Microsoft Office"], **fields}
    resp = await client.post(API, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_expiry_state():
    from app.features.license.crud import expiry_state

    today = date(2026, 11, 24)
    assert expiry_state(None, today, 60) == "none"
    assert expiry_state(today - timedelta(days=1), today, 60) == "expired"
    assert expiry_state(today, today, 60) == "soon"
    assert expiry_state(today + timedelta(days=60), today, 60) == "soon"
    assert expiry_state(today + timedelta(days=61), today, 60) == "active"


async def test_counts_each_poste_once_across_versions(client, db_session):
    sites = await two_sites(client, db_session)
    # Two versions and a second covered program on A: one installation.
    await _install(db_session, sites.a.id, "Microsoft Office LTSC 2021", "16.0.1")
    await _install(db_session, sites.a.id, "Microsoft Office LTSC 2021", "16.0.2")
    await _install(db_session, sites.a.id, "Microsoft Visio 2021")
    await _install(db_session, sites.b.id, "microsoft office lts 2021")
    await _install(db_session, sites.b.id, "LibreOffice")

    lic = await _create(
        client,
        sites.admin,
        patterns=["Microsoft Office", "Visio"],
        seats=1,
        vendor="UGAP",
        reference="CMD-2024-118",
    )
    assert lic["installed"] == 2
    assert lic["over"] is True
    assert lic["expiry"] == "none"

    detail = (await client.get(f"{API}/{lic['id']}", headers=sites.admin)).json()
    assert detail["programs"] == [
        "microsoft office lts 2021",
        "Microsoft Office LTSC 2021",
        "Microsoft Visio 2021",
    ]

    # The list's filter names the same postes.
    resp = await client.get(
        "/api/v1/machines", headers=sites.admin, params={"license_id": lic["id"]}
    )
    assert {m["hostname"] for m in resp.json()["items"]} == {"PC-A", "PC-B"}


async def test_pattern_is_literal_and_publisher_narrows(client, db_session):
    sites = await two_sites(client, db_session)
    await _install(db_session, sites.a.id, "Adobe Acrobat Reader", publisher="Adobe")
    await _install(db_session, sites.b.id, "Foxit PDF Reader", publisher="Foxit")
    await _install(db_session, sites.b.id, "Tool_X 100%")

    reader = await _create(
        client, sites.admin, name="Reader", patterns=["Reader"], publisher="adobe"
    )
    assert reader["installed"] == 1

    # « % » and « _ » are characters, not wildcards.
    resp = await client.post(
        f"{API}/preview", headers=sites.admin, json={"patterns": ["Foxit_PDF"]}
    )
    assert resp.json() == {"programs": [], "installed": 0}
    resp = await client.post(
        f"{API}/preview", headers=sites.admin, json={"patterns": ["0%"]}
    )
    assert resp.json() == {"programs": ["Tool_X 100%"], "installed": 1}


async def test_retired_postes_use_no_seat(client, db_session):
    from app.features.asset.models import Asset, AssetStatus

    sites = await two_sites(client, db_session)
    await _install(db_session, sites.a.id, "Microsoft Office")
    await _install(db_session, sites.b.id, "Microsoft Office")
    db_session.add(Asset(machine_id=sites.b.id, status=AssetStatus.RETIRED))
    await db_session.commit()

    lic = await _create(client, sites.admin, seats=1)
    assert lic["installed"] == 1
    assert lic["over"] is False


async def test_scoped_reader_counts_its_postes_without_verdict(client, db_session):
    sites = await two_sites(client, db_session)
    await _install(db_session, sites.a.id, "Microsoft Office")
    await _install(db_session, sites.b.id, "Microsoft Office")
    lic = await _create(client, sites.admin, seats=1)

    resp = await client.get(API, headers=sites.scoped)
    body = resp.json()
    assert body["restricted"] is True
    assert body["items"][0]["installed"] == 1
    assert body["items"][0]["over"] is None

    # Writing is for the whole parc.
    resp = await client.patch(
        f"{API}/{lic['id']}", headers=sites.scoped, json={"seats": 5}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.scope.restricted"
    resp = await client.post(
        API, headers=sites.scoped, json={"name": "X", "patterns": ["Xx"]}
    )
    assert resp.status_code == 403
    resp = await client.delete(f"{API}/{lic['id']}", headers=sites.scoped)
    assert resp.status_code == 403


async def test_rights_and_validation(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    sites = await two_sites(client, db_session)
    tech = await account(
        client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN]
    )
    # A technician does not read licences by default.
    assert (await client.get(API, headers=tech)).status_code == 403

    reader_group = await group(db_session, "Achats", {"license:read"}, None)
    reader = await account(client, db_session, "achats@test.local", [reader_group.id])
    assert (await client.get(API, headers=reader)).status_code == 200
    resp = await client.post(
        API, headers=reader, json={"name": "X", "patterns": ["Xx"]}
    )
    assert resp.status_code == 403

    # A pattern is needed, two characters at least; duplicates kept once.
    resp = await client.post(
        API, headers=sites.admin, json={"name": "X", "patterns": []}
    )
    assert resp.status_code == 422
    resp = await client.post(
        API, headers=sites.admin, json={"name": "X", "patterns": ["a"]}
    )
    assert resp.status_code == 422
    lic = await _create(
        client, sites.admin, patterns=["Office", " office ", "Visio"], seats=0
    )
    assert lic["patterns"] == ["Office", "Visio"]
    resp = await client.patch(
        f"{API}/{lic['id']}", headers=sites.admin, json={"patterns": None}
    )
    assert resp.status_code == 422
    resp = await client.patch(
        f"{API}/{lic['id']}", headers=sites.admin, json={"seats": -1}
    )
    assert resp.status_code == 422
    # No field for a key: an unknown field is ignored, never stored.
    resp = await client.patch(
        f"{API}/{lic['id']}",
        headers=sites.admin,
        json={"key": "XXXXX-XXXXX", "seats": None, "vendor": "  "},
    )
    assert resp.status_code == 200
    assert "key" not in resp.json()
    assert resp.json()["seats"] is None
    assert resp.json()["vendor"] is None
    assert resp.json()["over"] is False

    resp = await client.get(
        "/api/v1/machines",
        headers=sites.admin,
        params={"license_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "license.not_found"


async def test_writes_are_audited(client, db_session):
    from sqlmodel import select

    from app.features.audit.models import AuditEntry

    sites = await two_sites(client, db_session)
    lic = await _create(client, sites.admin, reference="CMD-1")
    await client.patch(f"{API}/{lic['id']}", headers=sites.admin, json={"seats": 3})
    resp = await client.delete(f"{API}/{lic['id']}", headers=sites.admin)
    assert resp.status_code == 204
    assert (
        await client.get(f"{API}/{lic['id']}", headers=sites.admin)
    ).status_code == 404

    rows = await db_session.exec(
        select(AuditEntry)
        .where(AuditEntry.resource_type == "license")
        .order_by(AuditEntry.at)
    )
    entries = rows.all()
    assert [e.action for e in entries] == [
        "license.create",
        "license.update",
        "license.delete",
    ]
    assert all(e.resource_id == lic["id"] for e in entries)
    assert entries[1].details["seats"] == "3"


async def test_expiry_threshold_follows_the_setting(client, db_session):
    sites = await two_sites(client, db_session)
    in_90 = (date.today() + timedelta(days=90)).isoformat()
    await _create(client, sites.admin, expires_on=in_90)
    body = (await client.get(API, headers=sites.admin)).json()
    assert body["expiry_days"] == 60
    assert body["items"][0]["expiry"] == "active"

    resp = await client.patch(
        "/api/v1/settings", headers=sites.admin, json={"license_expiry_days": 120}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["license_expiry_days"] == 120
    body = (await client.get(API, headers=sites.admin)).json()
    assert body["items"][0]["expiry"] == "soon"


async def test_digest_lists_licences_to_whoever_reads_them(client, db_session):
    from sqlmodel import select

    from app.features.notification import digest
    from app.features.user.models import User

    sites = await two_sites(client, db_session)
    await _install(db_session, sites.a.id, "Microsoft Office")
    await _install(db_session, sites.b.id, "Microsoft Office")
    await _create(client, sites.admin, name="Office", seats=1)
    past = (date.today() - timedelta(days=3)).isoformat()
    await _create(
        client, sites.admin, name="Antidote", patterns=["Antidote"], expires_on=past
    )
    await _create(client, sites.admin, name="Calm", patterns=["Calm"], seats=10)

    for email in ("admin@test.local", "tech-a@test.local"):
        user = (await db_session.exec(select(User).where(User.email == email))).one()
        user.email_preference = "digest_daily"
        db_session.add(user)
    await db_session.commit()

    planned = {p.user.email: p for p in await digest.plan_daily_digest(db_session)}
    admin = planned["admin@test.local"]
    assert [s.license.name for s in admin.licenses] == ["Antidote", "Office"]
    # Confined to a site: the parc's count is not its to read.
    assert planned["tech-a@test.local"].licenses == []

    _, body = digest.render_digest(admin.digest, [], None, admin.licenses)
    assert "LICENCES À REVOIR" in body
    assert "  Office : 2 installation(s) pour 1 licence(s)" in body
    day = (date.today() - timedelta(days=3)).strftime("%d/%m/%Y")
    assert f"  Antidote : échue depuis le {day}" in body
    assert "Calm" not in body

    from app.features.user.models import Language

    _, body = digest.render_digest(admin.digest, [], Language.EN, admin.licenses)
    assert "  Office: 2 installations for 1 licence" in body
