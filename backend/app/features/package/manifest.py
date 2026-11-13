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
from pathlib import Path

from app.features.package.models import Package, PackageFile

FORMAT = "tiai-package-1"

# The one word ``run`` may hold that is not a file of the package: an
# uninstall by product code. The agent resolves it to System32\msiexec.exe.
MSIEXEC = "msiexec"

# What a file of a package may be called: a plain file name, no path, nothing a
# Windows path would read as a device or a stream. Applied with fullmatch:
# "$" after re.match also accepts a trailing newline (audit S25).
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()+\-]{0,254}")
_RESERVED = re.compile(
    r"(con|prn|aux|nul|com\d|lpt\d)(\..*)?", re.IGNORECASE | re.DOTALL
)


def valid_file_name(name: str) -> bool:
    return (
        bool(_FILE_NAME.fullmatch(name))
        and not _RESERVED.fullmatch(name)
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


# What the agent refuses next to the executable under method A (agent
# deploy.loadableExt, audit S02): Windows could load or run it from there.
# The three lists (agent, server, console) are kept equal by a test.
LOADABLE_EXTENSIONS = frozenset(
    ".dll .ocx .cpl .sys .drv .ax .acm .ime .tsp .mui .tlb .winmd .manifest "
    ".local .config .exe .com .scr .pif .msi .msp .mst .msu .appx .msix .bat "
    ".cmd .ps1 .psm1 .vbs .vbe .js .jse .wsf .wsh .hta .lnk .inf .jar .bpl "
    ".pyd .xll .node .rll .wsc .sct".split()
)

# An MSI product code, the one argument method A lets msiexec take (agent
# deploy.productCode).
PRODUCT_CODE = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)


def runnable_somewhere(
    package: Package, files: Sequence[PackageFile], action: str = "install"
) -> bool:
    """Whether some poste could run this ``files`` package's installation —
    or uninstallation, ``action="uninstall"``: signed by the administrator
    (method B), or launched by an .exe whose publisher was read at upload
    with nothing loadable beside it (method A). Neither, and every poste will
    refuse it (audit B30).

    Method A also runs an uninstall by ``msiexec`` when one argument is a
    product code: the agent rebuilds the command line as ``/x {code} /qn
    /norestart`` and downloads nothing (agent deploy.MethodAStep, audit U04).
    An installation by msiexec is not accepted here under method A: the agent
    would turn it into that uninstall."""
    if package.signature is not None:
        return True
    if action == "uninstall":
        run = package.uninstall_run or ""
        if run == MSIEXEC:
            return any(PRODUCT_CODE.fullmatch(a) for a in package.uninstall_args)
    else:
        run = package.install_run or ""
    if not run.lower().endswith(".exe"):
        return False
    run_file = next((f for f in files if f.name == run), None)
    if run_file is None or not run_file.publisher_name:
        return False
    return not any(
        f.name != run and Path(f.name.lower()).suffix in LOADABLE_EXTENSIONS
        for f in files
    )


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
