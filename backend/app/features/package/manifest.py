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

from app.core.config import settings
from app.features.package import storage
from app.features.package.models import Package, PackageFile

FORMAT = "tiai-package-1"

# The one word ``run`` may hold that is not a file of the package: an
# uninstall by product code. The agent resolves it to System32\msiexec.exe.
MSIEXEC = "msiexec"

# What a file of a package may be called: a plain file name, no path, nothing a
# Windows path would read as a device or a stream. Applied with fullmatch:
# "$" after re.match also accepts a trailing newline (audit S25).
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()+\-]{0,254}")
# A device name is one whatever follows its first dot, and whatever spaces
# sit before that dot: Windows opens "nul .cab" as NUL (audit T38). The stem —
# the name up to its first dot — trimmed of trailing spaces, any case. The
# agent applies the same rule (deploy.ValidFileName).
_RESERVED = re.compile(
    r"(con|prn|aux|nul|com\d|lpt\d) *(\..*)?", re.IGNORECASE | re.DOTALL
)


def valid_file_name(name: str) -> bool:
    return (
        bool(_FILE_NAME.fullmatch(name))
        and not _RESERVED.fullmatch(name)
        and not name.endswith((".", " "))
    )


@dataclass(frozen=True)
class Problem:
    """Why a package cannot be deployed yet, in the console's words.

    ``blocks_uninstall``: whether it stands in the way of an uninstallation
    too. The agent reads the whole manifest before either step (deploy
    ParseManifest), so most do; a missing *install* step does not."""

    code: str
    message: str
    blocks_uninstall: bool = True


def _quoted(names: Sequence[str]) -> str:
    return ", ".join(f"« {n} »" for n in names)


def case_duplicates(files: Sequence[PackageFile]) -> list[list[str]]:
    """The file names that differ only by case, grouped. One file on Windows,
    and a manifest the agent refuses whole (deploy.ParseManifest, audit T23).
    An upload replaces such a file; rows written before that rule may remain."""
    groups: dict[str, list[str]] = {}
    for f in files:
        groups.setdefault(f.name.lower(), []).append(f.name)
    return [sorted(names) for _, names in sorted(groups.items()) if len(names) > 1]


def by_product_code(package: Package) -> bool:
    """Whether the uninstallation is ``msiexec`` with an MSI product code among
    its arguments: what method A runs as ``/x {code}`` without downloading any
    file of the package (agent deploy.MethodAStep)."""
    return package.uninstall_run == MSIEXEC and any(
        PRODUCT_CODE.fullmatch(a) for a in package.uninstall_args
    )


def problems(package: Package, files: Sequence[PackageFile]) -> list[Problem]:
    """What stands between this ``files`` package and a deployment."""
    out: list[Problem] = []
    names = {f.name for f in files}
    if not files:
        out.append(Problem("no_files", "Aucun fichier déposé"))
    if not package.install_run:
        # The one problem an uninstallation does not share: the agent runs
        # the uninstall step of a manifest that has no install step.
        out.append(
            Problem("no_install", "Fichier à lancer non choisi", blocks_uninstall=False)
        )
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
    duplicates = case_duplicates(files)
    if duplicates:
        out.append(
            Problem(
                "duplicate_names",
                "Fichiers dont le nom ne diffère que par la casse (un seul "
                "fichier sous Windows, les postes refusent le paquet) : "
                + " ; ".join(_quoted(group) for group in duplicates)
                + " — retirez ceux en trop",
            )
        )
    # A row whose stored file is gone: every poste would get a 404 on it. Left
    # by the store sweep of v1.2.0, which could delete a file an upload had
    # just stored (audit T09); uploading the file again restores it.
    lost = sorted({f.name for f in files if not storage.exists(f.sha256)})
    if lost:
        out.append(
            Problem(
                "file_missing_in_store",
                "Fichier absent du stockage du serveur : "
                + _quoted(lost)
                + " — déposez-le de nouveau",
                # Downloaded by every step but one: an unsigned package's
                # msiexec /x {code}, which method A runs without any file.
                blocks_uninstall=package.signature is not None
                or not by_product_code(package),
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


def method_a_max_bytes() -> int:
    """What an unsigned manifest may announce in all before the postes refuse
    it (agent deploy.MethodAFiles, registry DeployMethodAMaxGB)."""
    return settings.PACKAGE_METHOD_A_MAX_GB << 30


def method_a_too_large(files: Sequence[PackageFile]) -> bool:
    """Whether the files weigh more, together, than method A downloads. A
    signed package is not capped: its sizes are the administrator's word."""
    return sum(f.size for f in files) > method_a_max_bytes()


def runnable_somewhere(
    package: Package,
    files: Sequence[PackageFile],
    action: str = "install",
    *,
    capped: bool = True,
) -> bool:
    """Whether some poste could run this ``files`` package's installation —
    or uninstallation, ``action="uninstall"``: signed by the administrator
    (method B), or launched by an .exe whose publisher was read at upload
    with nothing loadable beside it and no more than the method A cap to
    download (method A). Neither, and every poste will refuse it (audit B30).
    ``capped=False`` leaves the size out: what tells "too large for method A"
    from "not method A at all".

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
            return by_product_code(package)
    else:
        run = package.install_run or ""
    if not run.lower().endswith(".exe"):
        return False
    run_file = next((f for f in files if f.name == run), None)
    if run_file is None or not run_file.publisher_name:
        return False
    if capped and method_a_too_large(files):
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
