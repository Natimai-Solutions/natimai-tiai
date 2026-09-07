"""Version ordering behind the "agent obsolète" flag (no database needed)."""

from app.features.machine.agent_version import (
    latest_version,
    outdated_versions,
    version_key,
)


def test_numeric_fields_compare_as_numbers():
    # The string compare gets this one wrong ("0.10.0" < "0.9.0").
    assert version_key("0.10.0") > version_key("0.9.0")
    assert version_key("1.0.0") > version_key("0.99.99")


def test_prerelease_sorts_below_its_release():
    assert version_key("0.5.0-dev.abc1234") < version_key("0.5.0")
    # …and above the previous release, which it postdates.
    assert version_key("0.5.0-dev.abc1234") > version_key("0.4.9")


def test_leading_v_is_ignored():
    assert version_key("v0.5.0") == version_key("0.5.0")


def test_unparseable_versions_rank_lowest():
    # A build from an untagged tree must never become the parc's reference.
    assert latest_version(["garbage", "0.1.0"]) == "0.1.0"


def test_latest_and_outdated():
    versions = ["0.4.1", "0.5.0", "0.5.0-dev.1", "0.3.9"]
    assert latest_version(versions) == "0.5.0"
    assert sorted(outdated_versions(versions, "0.5.0")) == [
        "0.3.9",
        "0.4.1",
        "0.5.0-dev.1",
    ]
    # A pinned reference below the fleet's best flags nothing above it.
    assert outdated_versions(versions, "0.4.1") == ["0.3.9"]


def test_empty_fleet():
    assert latest_version([]) is None
    assert latest_version(["", "  "]) is None
    assert outdated_versions(["0.1.0"], None) == []
