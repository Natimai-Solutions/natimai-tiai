"""Unit tests for the up-to-date computation (no database)."""

from app.features.machine.status import compute_is_up_to_date

MAX_AGE = 3


def test_protected_with_fresh_signatures_is_up_to_date():
    assert compute_is_up_to_date(
        av_enabled=True, rtp_enabled=True, signature_age_days=1, max_age_days=MAX_AGE
    )


def test_boundary_age_is_up_to_date():
    assert compute_is_up_to_date(
        av_enabled=True,
        rtp_enabled=True,
        signature_age_days=MAX_AGE,
        max_age_days=MAX_AGE,
    )


def test_stale_signatures_not_up_to_date():
    assert not compute_is_up_to_date(
        av_enabled=True, rtp_enabled=True, signature_age_days=10, max_age_days=MAX_AGE
    )


def test_protection_off_not_up_to_date():
    assert not compute_is_up_to_date(
        av_enabled=False, rtp_enabled=True, signature_age_days=0, max_age_days=MAX_AGE
    )
    assert not compute_is_up_to_date(
        av_enabled=True, rtp_enabled=False, signature_age_days=0, max_age_days=MAX_AGE
    )


def test_unknown_data_not_up_to_date():
    assert not compute_is_up_to_date(
        av_enabled=None, rtp_enabled=None, signature_age_days=None, max_age_days=MAX_AGE
    )
    assert not compute_is_up_to_date(
        av_enabled=True, rtp_enabled=True, signature_age_days=None, max_age_days=MAX_AGE
    )


# --- Third-party antivirus --------------------------------------------------
#
# A machine guarded by ESET or Bitdefender reports Defender as off, because
# Windows really has put it in passive mode. These cases are the reason
# compute_is_up_to_date has a second path at all.


def _third_party(**overrides):
    """Defender off (passive mode), with the third-party fields under test."""
    args = {
        "av_enabled": False,
        "rtp_enabled": False,
        "signature_age_days": None,
        "max_age_days": MAX_AGE,
        "av_product_is_defender": False,
        "av_product_enabled": True,
        "av_product_signatures_up_to_date": True,
    }
    return compute_is_up_to_date(**{**args, **overrides})


def test_running_third_party_antivirus_is_up_to_date():
    assert _third_party()


def test_third_party_with_unknown_signature_freshness_still_counts():
    """The freshness bit is optional in practice — vendors fill it in unevenly.

    Requiring a positive value would leave a whole fleet permanently "outdated",
    which is the bug this path exists to fix.
    """
    assert _third_party(av_product_signatures_up_to_date=None)


def test_third_party_reporting_stale_signatures_is_not_up_to_date():
    assert not _third_party(av_product_signatures_up_to_date=False)


def test_stopped_third_party_is_not_up_to_date():
    assert not _third_party(av_product_enabled=False)
    assert not _third_party(av_product_enabled=None)


def test_defender_entry_in_the_security_center_grants_nothing():
    """Defender's own registry entry must not stand in for its real state.

    Otherwise a machine whose signatures are three months old would pass on the
    strength of a bit, while the Defender columns hold actual dates.
    """
    assert not _third_party(av_product_is_defender=True)
    # Unknown is treated the same: a product the agent could not identify must
    # not be credited with protecting the machine.
    assert not _third_party(av_product_is_defender=None)


def test_machine_with_no_antivirus_at_all_is_not_up_to_date():
    assert not compute_is_up_to_date(
        av_enabled=False,
        rtp_enabled=False,
        signature_age_days=None,
        max_age_days=MAX_AGE,
        av_product_is_defender=False,
        av_product_enabled=None,
        av_product_signatures_up_to_date=None,
    )


def test_healthy_defender_still_wins_without_any_third_party():
    """The Defender path is untouched by the new arguments' defaults."""
    assert compute_is_up_to_date(
        av_enabled=True, rtp_enabled=True, signature_age_days=1, max_age_days=MAX_AGE
    )
