"""When a Windows version stops receiving security updates.

Read off the string the agent composes (``agent/internal/sysinfo``), e.g.
« Windows 11 Education 23H2 (Build 22631) »: the build says which release it
is, the product name says which servicing channel applies — the Home and Pro
editions (Pro Education and Pro for Workstations included) get 24 months per
release of Windows 11, Enterprise and Education 36, the LTSC editions their
own five years and the IoT Enterprise LTSC ones ten. The same build can
therefore be out of support on a Pro poste and still supported on an
Education one.

A table in the code, updated with each version of Tia'i: the server may have
no Internet access, and Microsoft publishes these dates years ahead. The
dates are Microsoft's published end-of-servicing dates for each release;
**re-check them against Microsoft's lifecycle pages when the table is
extended**. Paid extended security updates (ESU) are not known to the
console: a poste covered by them is still reported, and the rule can be
switched off.

What is not recognised — a server, an unknown build, an empty string — is
*unknown*, never « unsupported »: an alert on a guess is how a list of alerts
gets ignored.
"""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Channel(StrEnum):
    HOME_PRO = "home_pro"
    ENTERPRISE_EDUCATION = "enterprise_education"
    LTSC = "ltsc"
    # IoT Enterprise LTSC: the same builds as LTSC, serviced longer since 2021.
    IOT_LTSC = "iot_ltsc"


@dataclass(frozen=True)
class Support:
    """A recognised release. ``end`` is the last day it is serviced; None for
    the releases so old that only « ended » matters (Windows 10 before 1909)."""

    end: date | None

    def ended(self, today: date) -> bool:
        return self.end is None or today > self.end


# Build → end of servicing per channel. A channel missing from a row does not
# exist for that build (no LTSC of 22H2) and falls back to its general one.
_WINDOWS_10: dict[int, dict[Channel, date]] = {
    10240: {Channel.LTSC: date(2025, 10, 14)},  # LTSB 2015
    14393: {Channel.LTSC: date(2026, 10, 13)},  # LTSB 2016
    17763: {Channel.LTSC: date(2029, 1, 9)},  # LTSC 2019 (1809)
    18363: {  # 1909
        Channel.HOME_PRO: date(2021, 5, 11),
        Channel.ENTERPRISE_EDUCATION: date(2022, 5, 10),
    },
    19041: {  # 2004
        Channel.HOME_PRO: date(2021, 12, 14),
        Channel.ENTERPRISE_EDUCATION: date(2021, 12, 14),
    },
    19042: {  # 20H2
        Channel.HOME_PRO: date(2022, 5, 10),
        Channel.ENTERPRISE_EDUCATION: date(2023, 5, 9),
    },
    19043: {  # 21H1
        Channel.HOME_PRO: date(2022, 12, 13),
        Channel.ENTERPRISE_EDUCATION: date(2022, 12, 13),
    },
    19044: {  # 21H2, and LTSC 2021
        Channel.HOME_PRO: date(2023, 6, 13),
        Channel.ENTERPRISE_EDUCATION: date(2024, 6, 11),
        Channel.LTSC: date(2027, 1, 12),
        Channel.IOT_LTSC: date(2032, 1, 13),
    },
    19045: {  # 22H2, the last release of Windows 10
        Channel.HOME_PRO: date(2025, 10, 14),
        Channel.ENTERPRISE_EDUCATION: date(2025, 10, 14),
    },
}

_WINDOWS_11: dict[int, dict[Channel, date]] = {
    22000: {  # 21H2
        Channel.HOME_PRO: date(2023, 10, 10),
        Channel.ENTERPRISE_EDUCATION: date(2024, 10, 8),
    },
    22621: {  # 22H2
        Channel.HOME_PRO: date(2024, 10, 8),
        Channel.ENTERPRISE_EDUCATION: date(2025, 10, 14),
    },
    22631: {  # 23H2
        Channel.HOME_PRO: date(2025, 11, 11),
        Channel.ENTERPRISE_EDUCATION: date(2026, 11, 10),
    },
    26100: {  # 24H2, and LTSC 2024
        Channel.HOME_PRO: date(2026, 10, 13),
        Channel.ENTERPRISE_EDUCATION: date(2027, 10, 12),
        Channel.LTSC: date(2029, 10, 9),
        Channel.IOT_LTSC: date(2034, 10, 10),
    },
    26200: {  # 25H2
        Channel.HOME_PRO: date(2027, 10, 12),
        Channel.ENTERPRISE_EDUCATION: date(2028, 10, 10),
    },
}

# Before Windows 10, one date per product whatever the edition.
_OLDER: dict[int, date] = {
    7601: date(2020, 1, 14),  # Windows 7 SP1
    9200: date(2016, 1, 12),  # Windows 8
    9600: date(2023, 1, 10),  # Windows 8.1
}

# The oldest general release of Windows 10 the table lists (1909).
_OLDEST_WINDOWS_10_GENERAL = min(
    build for build, row in _WINDOWS_10.items() if Channel.HOME_PRO in row
)

_BUILD = re.compile(r"\(Build (\d+)")
_WORD = re.compile(r"[a-z]+")
# The first Windows 11 build: below it, a build is Windows 10 or older.
_FIRST_WINDOWS_11 = 22000


def channel_of(product: str) -> Channel:
    """The servicing channel a product name falls under."""
    words = set(_WORD.findall(product.lower()))
    if words & {"ltsc", "ltsb"}:
        return Channel.IOT_LTSC if "iot" in words else Channel.LTSC
    if "pro" in words:
        # Pro Education and Pro for Workstations: Microsoft services them
        # with Home and Pro, whatever « Education » says.
        return Channel.HOME_PRO
    if words & {"enterprise", "education"}:
        return Channel.ENTERPRISE_EDUCATION
    return Channel.HOME_PRO


def support_of(os_version: str | None) -> Support | None:
    """The servicing of the release ``os_version`` names, or None when it is
    not recognised (a server, an unknown or future build, no build at all)."""
    if not os_version:
        return None
    lowered = os_version.lower()
    if "server" in lowered or "windows" not in lowered:
        return None
    match = _BUILD.search(os_version)
    if match is None:
        return None
    build = int(match.group(1))
    if build in _OLDER:
        return Support(_OLDER[build])
    channel = channel_of(os_version)
    table = _WINDOWS_11 if build >= _FIRST_WINDOWS_11 else _WINDOWS_10
    row = table.get(build, {})
    if channel in row:
        return Support(row[channel])
    if channel is Channel.IOT_LTSC and Channel.LTSC in row:
        # Before 2021 an IoT LTSC/LTSB release ended with its Enterprise one.
        return Support(row[Channel.LTSC])
    if channel in (Channel.LTSC, Channel.IOT_LTSC):
        # An LTSC product on a build with no LTSC release: mislabelled, or a
        # release this table does not know. Not a guess to alert on.
        return None
    general = row.get(channel) or row.get(Channel.ENTERPRISE_EDUCATION)
    if general is not None:
        return Support(general)
    if build < _FIRST_WINDOWS_11 and build < _OLDEST_WINDOWS_10_GENERAL:
        # A general edition of Windows 10 older than any release listed
        # (1903 and before, or 1607 on a Pro poste): long out of support.
        return Support(None)
    # A build above the table is newer than this version of Tia'i.
    return None
