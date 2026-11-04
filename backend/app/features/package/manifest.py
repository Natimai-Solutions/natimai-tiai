"""The manifest of a ``files`` package: what method B signs.

The server writes it once per change and stores the bytes as written; the
signature covers those bytes and the agent parses them only after verifying.
Nothing has to reproduce a canonical form — which is the classic way such a
scheme breaks (two serialisers disagreeing on a space or a key order).
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.features.package.models import Package, PackageFile

FORMAT = "tiai-package-1"

# The one word ``run`` may hold that is not a file of the package: an
# uninstall by product code. The agent resolves it to System32\msiexec.exe.
MSIEXEC = "msiexec"

# What a file of a package may be called: a plain file name, no path, nothing a
# Windows path would read as a device or a stream.
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+\-]{0,254}$")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.IGNORECASE)


def valid_file_name(name: str) -> bool:
    return (
        bool(_FILE_NAME.match(name))
        and not _RESERVED.match(name)
        and not name.endswith((".", " "))
    )


@dataclass(frozen=True)
class Problem:
    """Why a package cannot be deployed yet, in the console's words."""

    code: str
    message: str


def problems(package: Package, files: Sequence[PackageFile]) -> list[Problem]:
    """What stands between this ``files`` package and a deployment."""
    out: list[Problem] = []
    names = {f.name for f in files}
    if not files:
        out.append(Problem("no_files", "Aucun fichier déposé"))
    if not package.install_run:
        out.append(Problem("no_install", "Fichier à lancer non choisi"))
    elif package.install_run != MSIEXEC and package.install_run not in names:
        out.append(
            Problem(
                "install_missing", f"« {package.install_run} » n'est pas dans le paquet"
            )
        )
    if (
        package.uninstall_run
        and package.uninstall_run != MSIEXEC
        and package.uninstall_run not in names
    ):
        out.append(
            Problem(
                "uninstall_missing",
                f"« {package.uninstall_run} » n'est pas dans le paquet",
            )
        )
    return out


def build(package: Package, files: Sequence[PackageFile]) -> bytes:
    """The manifest bytes for the package as it stands."""
    document = {
        "format": FORMAT,
        "package_id": str(package.id),
        "name": package.name,
        "version": package.version or "",
        "files": [
            {"name": f.name, "sha256": f.sha256, "size": f.size}
            for f in sorted(files, key=lambda f: f.name)
        ],
        "install": {"run": package.install_run, "args": list(package.install_args)}
        if package.install_run
        else None,
        "uninstall": {
            "run": package.uninstall_run,
            "args": list(package.uninstall_args),
        }
        if package.uninstall_run
        else None,
        "success_codes": list(package.success_codes),
    }
    # Indented and key-sorted for the administrator who opens it before
    # signing: it is a document somebody is meant to read.
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
