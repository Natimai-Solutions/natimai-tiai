"""Software deployment, defects found by the 2026-11 acceptance test: a
redeployment that sent nothing, simultaneous deployments, refusals that did
not say why, packages shown ready that no poste would run, a store sweep that
waited for a trigger, and what the console read in the deployments.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import base64
import hashlib
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlmodel import col, select

from tests.test_api_packages import (
    _admin,
    _cert,
    _command,
    _deploy,
    _enroll,
    _pronote,
    _signature_document,
    signed_pe,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PACKAGES_DIR", str(tmp_path / "packages"))
    return tmp_path / "packages"


async def _heartbeat(client, agent):
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    assert hb.status_code == 200, hb.text
    return hb.json()["commands"]


async def _upload(client, admin, package_id, *files):
    return await client.post(
        f"/api/v1/packages/{package_id}/files",
        headers=admin,
        files=[("files", f) for f in files],
    )


async def _files_package(client, admin, name="Outil", **fields):
    resp = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": name, **fields},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _commands_of(db_session, package_id):
    from app.features.command.models import Command

    db_session.expire_all()
    rows = await db_session.exec(
        select(Command).where(col(Command.package_id) == package_id)
    )
    return list(rows.all())


async def _deploy_many(client, admin, package_id, machine_ids):
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": machine_ids,
            "package_id": package_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- 1. a redeployment after a change replaces what still waits ---------------------


async def test_redeploying_a_changed_package_replaces_the_pending_deployments(
    client, db_session, store
):
    """« Rien à envoyer : déjà en attente », then « paquet modifié après la mise
    en file » at delivery: the redeployment did nothing. Now the stale pending
    ones are failed at once and new ones queued; a delivered one is left to
    run; an identical pending one still counts as already pending."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    waiting = [await _enroll(client, f"poste-{i}") for i in range(2)]
    running_id, running_agent = await _enroll(client, "poste-running")
    first = await _deploy_many(
        client, admin, package["id"], [m for m, _ in waiting] + [running_id]
    )
    assert first["count"] == 3
    (delivered,) = await _heartbeat(client, running_agent)

    changed = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_args": ["-s", "-f1{dir}\\ClientPRONOTE.iss", "/v2"]},
    )
    assert changed.status_code == 200, changed.text

    again = await _deploy_many(
        client, admin, package["id"], [m for m, _ in waiting] + [running_id]
    )
    # Two replaced and queued anew; the delivered one is still open.
    assert again["count"] == 2
    assert again["skipped"] == 1
    rows = await _commands_of(db_session, package["id"])
    superseded = [r for r in rows if r.error == "Remplacée par un nouveau déploiement"]
    assert len(superseded) == 2
    assert all(r.status == "failed" and r.finished_at for r in superseded)
    assert next(r for r in rows if str(r.id) == delivered["id"]).status == "delivered"

    # The same version once more: already pending, nothing replaced.
    third = await _deploy_many(client, admin, package["id"], [m for m, _ in waiting])
    assert third["count"] == 0
    assert third["skipped"] == 2
    assert len(await _commands_of(db_session, package["id"])) == 5

    # What goes out is the new version, once.
    for _, agent in waiting:
        (command,) = await _heartbeat(client, agent)
        manifest = base64.b64decode(command["package"]["manifest"])
        assert b"/v2" in manifest


async def test_superseding_stays_on_the_postes_targeted(client, db_session, store):
    """A redeployment to one poste does not touch another poste's pending
    deployment of the older version: it is not part of the request."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    one, _ = await _enroll(client, "poste-1")
    two, _ = await _enroll(client, "poste-2")
    await _deploy_many(client, admin, package["id"], [one, two])
    await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_args": ["/autre"]},
    )
    await _deploy_many(client, admin, package["id"], [one])
    assert (await _command(client, admin, two))["status"] == "pending"


# --- 2. simultaneous deployments of one package ---------------------------------------


async def test_simultaneous_deployments_queue_one_per_poste(
    client, db_session, store, monkeypatch
):
    """Six identical requests at once used to queue six installations per
    poste. Each request is held where it checks what is already open until
    the others arrive there too, or a moment passes: without the package
    lock they all meet there, and all queue."""
    from app.features.command import crud as command_crud

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machines = [(await _enroll(client, f"poste-{i}"))[0] for i in range(2)]

    original = command_crud.machines_with_open_command
    arrived = 0
    everyone = asyncio.Event()

    async def meeting(session, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 6:
            everyone.set()
        try:
            await asyncio.wait_for(everyone.wait(), timeout=0.3)
        except TimeoutError:
            pass
        return await original(session, **kwargs)

    monkeypatch.setattr(command_crud, "machines_with_open_command", meeting)
    answers = await asyncio.gather(
        *(_deploy_many(client, admin, package["id"], machines) for _ in range(6))
    )
    assert sum(a["count"] for a in answers) == 2
    assert sum(a["skipped"] for a in answers) == 10
    assert len(await _commands_of(db_session, package["id"])) == 2


# --- 3. a refused signature says why -------------------------------------------------


def _der(cert) -> str:
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()


async def test_each_refused_signature_says_why(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    url = f"/api/v1/packages/{package['id']}"
    stale_manifest = (await client.get(f"{url}/manifest", headers=admin)).content
    changed = await client.patch(url, headers=admin, json={"install_args": ["/new"]})
    assert changed.status_code == 200
    manifest = (await client.get(f"{url}/manifest", headers=admin)).content

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_cert = _cert(rsa_key, "Tiai RSA")
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_cert = _cert(other_key, "Autre")
    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_cert = _cert(ec_key, "Tiai EC")

    good = _signature_document(manifest, rsa_key, rsa_cert)
    cases = {
        "stale": _signature_document(stale_manifest, rsa_key, rsa_cert),
        "other_certificate": {**good, "certificate": _der(other_cert)},
        "wrong_algorithm": {**good, "certificate": _der(ec_cert)},
        "unreadable_certificate": {
            **good,
            "certificate": base64.b64encode(b"not a certificate").decode(),
        },
        "bad_base64_signature": {**good, "signature": "%%%"},
        "bad_base64_certificate": {**good, "certificate": "%%%"},
        "unknown_format": {**good, "format": "autre"},
        "unknown_algorithm": {**good, "algorithm": "md5"},
        "array": [good],
    }
    expected = {
        "stale": "le paquet a changé",
        "other_certificate": "autre certificat",
        "wrong_algorithm": "ne correspond pas à la clé du certificat (clé ECDSA)",
        "unreadable_certificate": "Certificat illisible",
        "bad_base64_signature": "La signature n'est pas encodé",
        "bad_base64_certificate": "Le certificat n'est pas encodé",
        "unknown_format": "Format de signature inconnu",
        "unknown_algorithm": "non pris en charge",
        "array": "n'est pas un objet JSON",
    }
    messages = {}
    for case, document in cases.items():
        resp = await client.put(f"{url}/signature", headers=admin, json=document)
        assert resp.status_code == 422, (case, resp.text)
        error = resp.json()["error"]
        assert error["code"] == "package.signature.invalid", (case, error)
        assert expected[case] in error["message"], (case, error["message"])
        messages[case] = error["message"]
    # One sentence per reason.
    assert len(set(messages.values())) == len(messages)

    # And the good one still goes through.
    ok = await client.put(f"{url}/signature", headers=admin, json=good)
    assert ok.status_code == 200, ok.text


async def test_an_ecdsa_mismatch_names_both_causes(client, db_session, store):
    """ECDSA cannot tell a changed manifest from another key: both are said."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    url = f"/api/v1/packages/{package['id']}"
    key = ec.generate_private_key(ec.SECP256R1())
    document = _signature_document(b"another manifest", key, _cert(key, "Tiai"))
    resp = await client.put(f"{url}/signature", headers=admin, json=document)
    assert resp.status_code == 422
    message = resp.json()["error"]["message"]
    assert "manifeste a changé" in message and "autre certificat" in message


# --- 5. what no poste would run is not « Prêt » ---------------------------------------


async def test_install_blockers_say_why_no_poste_would_install(
    client, db_session, store
):
    admin = await _admin(client, db_session)
    ready = await _pronote(client, admin)
    assert ready["install_blockers"] == []

    winget = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "Firefox", "winget_id": "Mozilla.Firefox"},
    )
    assert winget.json()["install_blockers"] == []

    # An unsigned .exe alone: method A needs an editor's signature on it.
    unsigned = await _files_package(client, admin, install_run="setup.exe")
    body = (
        await _upload(client, admin, unsigned["id"], ("setup.exe", b"MZ not signed"))
    ).json()
    assert body["problems"] == []
    (blocker,) = body["install_blockers"]
    assert "« setup.exe » ne porte pas de signature d'éditeur" in blocker

    # Editor-signed setup.exe with an unsigned helper.dll beside it.
    sidecar = await _files_package(
        client, admin, name="Sidecar", install_run="setup.exe"
    )
    body = (
        await _upload(
            client,
            admin,
            sidecar["id"],
            ("setup.exe", signed_pe("Editeur SAS")),
            ("helper.dll", b"MZ dll"),
        )
    ).json()
    assert body["publisher_name"] == "Editeur SAS"
    (blocker,) = body["install_blockers"]
    assert "« helper.dll » est à côté de « setup.exe »" in blocker

    # The deployment is refused with the same sentence.
    machine_id, _ = await _enroll(client, "poste-1")
    for package, sentence in ((unsigned, "setup.exe"), (sidecar, "helper.dll")):
        refused = await client.post(
            "/api/v1/commands",
            headers=admin,
            json={
                "type": "package_install",
                "machine_ids": [machine_id],
                "package_id": package["id"],
            },
        )
        assert refused.status_code == 409, refused.text
        problems = refused.json()["error"]["details"]["problems"]
        listed = (
            await client.get(f"/api/v1/packages/{package['id']}", headers=admin)
        ).json()["install_blockers"]
        assert problems == listed
        assert sentence in problems[0]

    # The problems come first, as the refusal gives them.
    empty = await _files_package(client, admin, name="Vide")
    assert empty["install_blockers"] == [p["message"] for p in empty["problems"]]
    # The list carries them too.
    listed = await client.get("/api/v1/packages", headers=admin)
    by_id = {p["id"]: p for p in listed.json()}
    assert by_id[unsigned["id"]]["install_blockers"]
    assert by_id[ready["id"]]["install_blockers"] == []


# --- 6. a refused file name says which, and why ---------------------------------------


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("nul.txt", "nom réservé par Windows"),
        ("_config.ini", "doit commencer par une lettre sans accent ou un chiffre"),
        ("été.ini", "caractère interdit « é »"),
        ("a#b;c.txt", "caractères interdits « # », « ; »"),
        ("fin.", "ni par un point ni par une espace"),
    ],
)
async def test_a_refused_file_name_is_named_with_its_reason(
    client, db_session, store, name, reason
):
    admin = await _admin(client, db_session)
    package = await _files_package(client, admin)
    resp = await _upload(client, admin, package["id"], (name, b"x"))
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "package.file.name_invalid"
    assert error["message"].startswith(f"« {name} » refusé : ")
    assert reason in error["message"]
    assert error["details"]["name"] == name
    assert reason in error["details"]["reason"]


def test_the_reasons_follow_the_rule_exactly():
    """``file_name_problem`` reads ``valid_file_name`` clause by clause: never
    a reason for an accepted name, always one for a refused name."""
    from app.features.package import manifest

    names = [
        "setup.exe",
        "Client PRONOTE (x64).msi",
        "a+b-c_d.e",
        "nul.txt",
        "NUL .cab",
        "com1",
        "lpt9.log",
        "con",
        "console.exe",
        "_config.ini",
        ".hidden",
        " lead.txt",
        "trail.",
        "trail ",
        "été.ini",
        "a\nb",
        "setup.exe\n",
        "x" * 255,
        "x" * 256,
        "",
        "a b",
        "-x",
    ]
    for name in names:
        assert manifest.valid_file_name(name) == (
            manifest.file_name_problem(name) is None
        ), repr(name)
    assert manifest.file_name_problem("a\nb") == (
        "caractère interdit U+000A (permis : lettres sans accent, chiffres, "
        "espaces et . _ - ( ) +)"
    )


async def test_two_spellings_in_one_request_name_both(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _files_package(client, admin)
    resp = await _upload(client, admin, package["id"], ("A.ini", b"1"), ("a.ini", b"2"))
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["message"].startswith("« a.ini » refusé : même nom que « A.ini »")
    assert error["details"]["reason"]


async def test_the_file_to_run_is_refused_with_its_reason(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "X", "install_run": "nul.exe"},
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "package.invalid"
    assert error["message"].startswith(
        "Fichier à lancer « nul.exe » refusé : nom réservé"
    )


# --- 8. a replaced file goes without waiting for a trigger ---------------------------


async def _replaced_file_held_by_a_pending_deployment(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    old_sha = hashlib.sha256(b"[InstallShield Silent]\n").hexdigest()
    replaced = await _upload(client, admin, package["id"], ("ClientPRONOTE.iss", b"v2"))
    assert replaced.status_code == 200, replaced.text
    assert (store / old_sha).exists()
    return admin, package, machine_id, agent, old_sha


async def test_a_refusal_at_delivery_releases_the_files(client, db_session, store):
    (
        admin,
        package,
        machine_id,
        agent,
        old_sha,
    ) = await _replaced_file_held_by_a_pending_deployment(client, db_session, store)
    assert await _heartbeat(client, agent) == []
    assert (await _command(client, admin, machine_id))["status"] == "failed"
    assert not (store / old_sha).exists()
    current = await client.get(f"/api/v1/packages/{package['id']}", headers=admin)
    for f in current.json()["files"]:
        assert (store / f["sha256"]).exists()


async def test_the_periodic_sweep_releases_an_expired_deployments_files(
    client, db_session, store, engine
):
    """Expired on a poste that stayed off, nothing else triggered a sweep: the
    API's own periodic sweep marks it expired and deletes the file."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.base import utcnow
    from app.features.command.models import Command
    from app.features.package import crud

    admin, package, _, _, old_sha = await _replaced_file_held_by_a_pending_deployment(
        client, db_session, store
    )
    (command,) = await _commands_of(db_session, package["id"])
    command_id = command.id
    command.expires_at = utcnow() - timedelta(minutes=1)
    db_session.add(command)
    await db_session.commit()

    task = asyncio.create_task(
        crud.sweep_periodically(lambda: AsyncSession(engine), interval_seconds=0.01)
    )
    try:
        for _ in range(300):
            if not (store / old_sha).exists():
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not (store / old_sha).exists()
    db_session.expire_all()
    assert (await db_session.get(Command, command_id)).status == "expired"
    current = await client.get(f"/api/v1/packages/{package['id']}", headers=admin)
    for f in current.json()["files"]:
        assert (store / f["sha256"]).exists()


async def test_a_superseded_deployment_releases_the_files(client, db_session, store):
    """The pending deployment a redeployment replaces was the last one
    holding the file replaced in the package: the file goes with that
    request, not at the next hourly sweep."""
    (
        admin,
        package,
        machine_id,
        _,
        old_sha,
    ) = await _replaced_file_held_by_a_pending_deployment(client, db_session, store)
    again = await _deploy_many(client, admin, package["id"], [machine_id])
    assert again["count"] == 1
    assert not (store / old_sha).exists()
    current = await client.get(f"/api/v1/packages/{package['id']}", headers=admin)
    for f in current.json()["files"]:
        assert (store / f["sha256"]).exists()


def _sweepers() -> list[asyncio.Task]:
    """The tasks running the periodic sweep, in this event loop."""
    return [
        t
        for t in asyncio.all_tasks()
        if getattr(t.get_coro(), "__name__", "") == "sweep_periodically"
    ]


async def test_the_api_sweeps_the_store_when_it_starts_and_while_it_runs(
    client, db_session, store, engine, monkeypatch
):
    """The lifespan of the API, as uvicorn runs it: one sweep at start-up,
    then the periodic one — started there, and stopped with the API. Without
    it a quiet server kept a replaced file until its next restart."""
    from app.core import db
    from app.features.package import crud
    from app.main import app

    admin = await _admin(client, db_session)
    await _pronote(client, admin)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(crud, "SWEEP_INTERVAL_SECONDS", 0.05)
    before = store / ("e0" * 32)
    before.write_bytes(b"an orphan left while the API was down")
    assert _sweepers() == []

    async with app.router.lifespan_context(app):
        assert not before.exists()
        (sweeper,) = _sweepers()
        meanwhile = store / ("e1" * 32)
        meanwhile.write_bytes(b"an orphan made after start-up")
        for _ in range(200):
            if not meanwhile.exists():
                break
            await asyncio.sleep(0.05)
        assert not meanwhile.exists()
        assert not sweeper.done()
    assert sweeper.cancelled()
    assert _sweepers() == []


async def test_the_periodic_sweep_survives_a_failing_round(store, monkeypatch):
    """A round that fails is logged; the next one runs."""
    from app.features.package import crud

    rounds = 0

    class Broken:
        async def __aenter__(self):
            nonlocal rounds
            rounds += 1
            raise RuntimeError("database down")

        async def __aexit__(self, *exc):
            return False

    task = asyncio.create_task(crud.sweep_periodically(Broken, interval_seconds=0.01))
    for _ in range(200):
        if rounds >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rounds >= 2


# --- 4. retiring: how many installs it cancels ----------------------------------------


async def test_the_summary_counts_the_installs_a_retirement_cancels(
    client, db_session, store
):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machines = [await _enroll(client, f"poste-{i}") for i in range(3)]
    await _deploy_many(client, admin, package["id"], [m for m, _ in machines])
    await _heartbeat(client, machines[0][1])
    summary = await client.get(
        "/api/v1/commands/package-summary",
        headers=admin,
        params={"package_id": package["id"]},
    )
    assert summary.json()["pending_installs"] == 2
    await client.post(f"/api/v1/packages/{package['id']}/retire", headers=admin)
    summary = await client.get(
        "/api/v1/commands/package-summary",
        headers=admin,
        params={"package_id": package["id"]},
    )
    assert summary.json()["pending_installs"] == 0


async def test_the_retirement_count_leaves_pending_uninstalls_out(
    client, db_session, store
):
    """A retirement cancels the installations still waiting, and leaves the
    uninstallations alone: the count the console announces before asking
    says the same."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    patched = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"uninstall_run": "Install_PRNclient.exe", "uninstall_args": ["-x"]},
    )
    assert patched.status_code == 200, patched.text
    machines = [m for m, _ in [await _enroll(client, f"poste-{i}") for i in range(3)]]
    await _deploy_many(client, admin, package["id"], machines[:2])
    for machine_id in machines[1:]:
        queued = await client.post(
            "/api/v1/commands",
            headers=admin,
            json={
                "type": "package_uninstall",
                "machine_ids": [machine_id],
                "package_id": package["id"],
            },
        )
        assert queued.status_code == 200, queued.text
        assert queued.json()["count"] == 1

    async def summary():
        resp = await client.get(
            "/api/v1/commands/package-summary",
            headers=admin,
            params={"package_id": package["id"]},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # Four commands wait — two of each kind — on three postes.
    before = await summary()
    assert before["by_status"] == {"pending": 3}
    assert before["pending_installs"] == 2
    retired = await client.post(
        f"/api/v1/packages/{package['id']}/retire", headers=admin
    )
    assert retired.status_code == 200, retired.text
    after = await summary()
    assert after["pending_installs"] == 0
    rows = await _commands_of(db_session, package["id"])
    assert sorted((r.type, r.status) for r in rows) == [
        ("package_install", "failed"),
        ("package_install", "failed"),
        ("package_uninstall", "pending"),
        ("package_uninstall", "pending"),
    ]


# --- 9. what the console reads ---------------------------------------------------------


async def test_one_missing_file_named_by_both_steps_is_said_once(client, db_session):
    admin = await _admin(client, db_session)
    package = await _files_package(
        client,
        admin,
        install_run="SETUP.EXE",
        uninstall_run="SETUP.EXE",
        uninstall_args=["/u"],
    )
    messages = [p["message"] for p in package["problems"]]
    assert messages.count("« SETUP.EXE » n'est pas dans le paquet") == 1


async def test_a_manifest_named_in_another_script_keeps_a_file_name(
    client, db_session, store
):
    admin = await _admin(client, db_session)
    package = await _files_package(
        client, admin, name="Блокнот", install_run="setup.exe"
    )
    await _upload(client, admin, package["id"], ("setup.exe", signed_pe("E")))
    resp = await client.get(f"/api/v1/packages/{package['id']}/manifest", headers=admin)
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert f'filename="{package["id"]}.tiai-manifest.json"' in disposition

    versioned = await client.patch(
        f"/api/v1/packages/{package['id']}", headers=admin, json={"version": "1.0"}
    )
    assert versioned.status_code == 200
    resp = await client.get(f"/api/v1/packages/{package['id']}/manifest", headers=admin)
    assert (
        f'filename="{package["id"]}-1.0.tiai-manifest.json"'
        in resp.headers["content-disposition"]
    )
    # A name that keeps its letters keeps its old file name.
    pronote = await _pronote(client, admin)
    resp = await client.get(f"/api/v1/packages/{pronote['id']}/manifest", headers=admin)
    assert (
        'filename="Client-PRONOTE-2026.2.8.tiai-manifest.json"'
        in (resp.headers["content-disposition"])
    )


async def test_a_batch_reads_by_poste_name_and_names_its_package(
    client, db_session, store
):
    """C5 and the deployments table: one batch by hostname, newest batch
    first; each row says which package it carries."""
    from app.core.config import settings

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    ids = {}
    for hostname in ("PC-C", "PC-A", "PC-D", "PC-B"):
        enroll = await client.post(
            "/api/v1/agent/enroll",
            headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
            json={"machine_uuid": f"uuid-{hostname}", "hostname": hostname},
        )
        assert enroll.status_code == 200, enroll.text
        ids[hostname] = enroll.json()["machine_id"]
    await _deploy_many(client, admin, package["id"], [ids["PC-D"], ids["PC-B"]])
    await _deploy_many(
        client, admin, package["id"], [ids["PC-C"], ids["PC-A"], ids["PC-D"]]
    )
    listed = await client.get(
        "/api/v1/commands", headers=admin, params={"package_id": package["id"]}
    )
    items = listed.json()["items"]
    # Second batch (PC-D already pending: skipped) then the first.
    assert [i["machine_hostname"] for i in items] == ["PC-A", "PC-C", "PC-B", "PC-D"]
    assert {i["package_name"] for i in items} == {"Client PRONOTE 2026.2.8"}

    on_poste = await client.get(
        "/api/v1/commands", headers=admin, params={"machine_id": ids["PC-A"]}
    )
    (row,) = on_poste.json()["items"]
    assert row["package_name"] == "Client PRONOTE 2026.2.8"


async def test_latest_lists_each_postes_latest_deployment(client, db_session, store):
    """The chip « En attente : N » filters the table to N rows: each poste's
    latest deployment, not every attempt behind it."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    one, _ = await _enroll(client, "poste-1")
    two, _ = await _enroll(client, "poste-2")
    await _deploy_many(client, admin, package["id"], [one, two])
    await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_args": ["/b"]},
    )
    await _deploy_many(client, admin, package["id"], [one])
    params = {"package_id": package["id"], "status": "pending"}
    every = await client.get("/api/v1/commands", headers=admin, params=params)
    assert every.json()["total"] == 2
    failed = await client.get(
        "/api/v1/commands",
        headers=admin,
        params={"package_id": package["id"], "status": "failed"},
    )
    assert failed.json()["total"] == 1
    latest_failed = await client.get(
        "/api/v1/commands",
        headers=admin,
        params={"package_id": package["id"], "status": "failed", "latest": True},
    )
    # The failed row is poste 1's older attempt: not its latest.
    assert latest_failed.json()["total"] == 0
    summary = await client.get(
        "/api/v1/commands/package-summary",
        headers=admin,
        params={"package_id": package["id"]},
    )
    assert summary.json()["by_status"] == {"pending": 2}
    latest = await client.get(
        "/api/v1/commands",
        headers=admin,
        params={"package_id": package["id"], "latest": True},
    )
    assert latest.json()["total"] == summary.json()["postes"]


@pytest.mark.parametrize(
    ("field", "limit"),
    [("name", 200), ("version", 100), ("detect_name", 200), ("notes", 5000)],
)
async def test_a_too_long_field_is_refused_in_french(client, db_session, field, limit):
    admin = await _admin(client, db_session)
    payload = {"kind": "winget", "name": "Firefox", "winget_id": "Mozilla.Firefox"}
    resp = await client.post(
        "/api/v1/packages", headers=admin, json={**payload, field: "x" * (limit + 1)}
    )
    assert resp.status_code == 422, resp.text
    (error,) = resp.json()["error"]["details"]["errors"]
    assert error["loc"][-1] == field
    assert error["msg"] == f"Value error, {limit} caractères au plus"
    at_limit = await client.post(
        "/api/v1/packages", headers=admin, json={**payload, field: "x" * limit}
    )
    assert at_limit.status_code == 201, at_limit.text


async def test_a_blank_or_null_name_is_refused_in_french(client, db_session):
    admin = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "Firefox", "winget_id": "Mozilla.Firefox"},
    )
    url = f"/api/v1/packages/{created.json()['id']}"
    for name in ("   ", None):
        resp = await client.patch(url, headers=admin, json={"name": name})
        assert resp.status_code == 422, (name, resp.text)
        (error,) = resp.json()["error"]["details"]["errors"]
        assert error["msg"] == "Value error, nom requis"


@pytest.mark.parametrize("field", ["install_args", "uninstall_args", "success_codes"])
async def test_a_null_list_is_refused_like_a_null_name(client, db_session, field):
    """``null`` is no list of arguments nor of exit codes. On a package whose
    manifest does not read the field — no step of that name, or a winget
    package — it used to be stored as JSON ``null``, and the whole catalogue
    then answered 500 for everyone."""
    admin = await _admin(client, db_session)
    winget = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "Firefox", "winget_id": "Mozilla.Firefox"},
    )
    files = await _files_package(client, admin)
    for package in (winget.json(), files):
        url = f"/api/v1/packages/{package['id']}"
        resp = await client.patch(url, headers=admin, json={field: None})
        assert resp.status_code == 422, (package["kind"], resp.text)
        (error,) = resp.json()["error"]["details"]["errors"]
        assert error["loc"][-1] == field
        assert error["msg"].startswith("Value error, ")
        assert (await client.get(url, headers=admin)).json()[field] == package[field]
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "Autre", field: None},
    )
    assert created.status_code == 422, created.text
    listed = await client.get("/api/v1/packages", headers=admin)
    assert [p["name"] for p in listed.json()] == ["Firefox", "Outil"]


async def test_a_stored_null_list_does_not_take_the_catalogue_down(
    client, db_session, store
):
    """A row that already holds a JSON ``null`` — written before ``null`` was
    refused — reads as an empty list: the catalogue lists, the package shows,
    and the console can save it again."""
    from sqlalchemy import text

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    url = f"/api/v1/packages/{package['id']}"
    await db_session.exec(
        text(
            "UPDATE packages SET install_args = 'null', uninstall_args = 'null', "
            "success_codes = 'null'"
        )
    )
    await db_session.commit()

    listed = await client.get("/api/v1/packages", headers=admin)
    assert listed.status_code == 200, listed.text
    (got,) = listed.json()
    assert (got["install_args"], got["uninstall_args"], got["success_codes"]) == (
        [],
        [],
        [],
    )
    assert (await client.get(url, headers=admin)).status_code == 200
    # Every route that rebuilds the manifest reads the row as well: a change
    # that leaves the nulls where they are, then msiexec steps over them.
    noted = await client.patch(url, headers=admin, json={"notes": "relu"})
    assert noted.status_code == 200, noted.text
    stepped = await client.patch(
        url, headers=admin, json={"install_run": "msiexec", "uninstall_run": "msiexec"}
    )
    assert stepped.status_code == 422, stepped.text
    assert stepped.json()["error"]["code"] == "package.invalid"
    manifest = await client.get(f"{url}/manifest", headers=admin)
    assert manifest.status_code == 200, manifest.text
    saved = await client.patch(
        url, headers=admin, json={"install_args": ["-s"], "success_codes": [0]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["install_args"] == ["-s"]

    # msiexec steps over nulls, which only a hand on the database writes:
    # the rules that read the arguments read none.
    await db_session.exec(
        text(
            "UPDATE packages SET install_run = 'msiexec', install_args = 'null', "
            "uninstall_run = 'msiexec', uninstall_args = 'null'"
        )
    )
    await db_session.commit()
    listed = await client.get("/api/v1/packages", headers=admin)
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["install_args"] == []
    renamed = await client.patch(url, headers=admin, json={"version": "2"})
    assert renamed.status_code == 422, renamed.text
    assert "msiexec" in renamed.json()["error"]["message"]
    machine_id, _ = await _enroll(client, "poste-1")
    refused = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_uninstall",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "package.not_ready"
