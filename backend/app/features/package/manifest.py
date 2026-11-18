"""The manifest of a ``files`` package: what method B signs.

The server writes it once per change and stores the bytes as written; the
signature covers those bytes and the agent parses them only after verifying.
Nothing has to reproduce a canonical form — which is the classic way such a
scheme breaks (two serialisers disagreeing on a space or a key order).
"""

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.features.package import storage
from app.features.package.models import Package, PackageFile, PackageKind

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


# One character of a file name, as ``_FILE_NAME`` admits it anywhere but first.
_NAME_CHAR = re.compile(r"[A-Za-z0-9 ._()+\-]")
ALLOWED_CHARACTERS = "lettres sans accent, chiffres, espaces et . _ - ( ) +"


def _shown(char: str) -> str:
    """A character as a sentence can show it: itself, or its code point when
    it would not show (a control, a space of another kind)."""
    return (
        f"« {char} »"
        if char.isprintable() and not char.isspace()
        else f"U+{ord(char):04X}"
    )


@dataclass(frozen=True)
class NameRefusal:
    """Why ``valid_file_name`` refuses a name: ``code`` and ``params`` for the
    console to word (plan ``dev/plan-console-bilingue.md``), ``message`` in
    French as the API always said it."""

    code: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)


def file_name_refusal(name: str) -> NameRefusal | None:
    """Why ``valid_file_name`` refuses this name, None when it is accepted.
    The same rule, read clause by clause, so that the administrator learns
    which one: a name made of allowed characters only may still start with
    one that may not lead, or be a device name (audit: « _config.ini »,
    « nul.txt »)."""
    if not name:
        return NameRefusal("empty", "nom vide")
    bad = list(dict.fromkeys(c for c in name if not _NAME_CHAR.fullmatch(c)))
    if bad:
        return NameRefusal(
            "forbidden_characters",
            "caractère"
            + ("s" if len(bad) > 1 else "")
            + " interdit"
            + ("s" if len(bad) > 1 else "")
            + " "
            + ", ".join(_shown(c) for c in bad)
            + f" (permis : {ALLOWED_CHARACTERS})",
            # As shown, quotes aside: a control or an odd space by its code point.
            {
                "characters": [
                    c if c.isprintable() and not c.isspace() else f"U+{ord(c):04X}"
                    for c in bad
                ]
            },
        )
    if len(name) > 255:
        return NameRefusal("too_long", "plus de 255 caractères", {"max": 255})
    if not name[0].isascii() or not name[0].isalnum():
        return NameRefusal(
            "bad_first_character",
            "le nom doit commencer par une lettre sans accent ou un chiffre",
        )
    if _RESERVED.fullmatch(name):
        return NameRefusal(
            "reserved",
            "nom réservé par Windows (CON, PRN, AUX, NUL, COM1 à COM9, LPT1 à "
            "LPT9, quelle que soit l'extension)",
        )
    if name.endswith((".", " ")):
        return NameRefusal(
            "bad_ending", "le nom ne doit finir ni par un point ni par une espace"
        )
    return None


def file_name_problem(name: str) -> str | None:
    """``file_name_refusal``'s French sentence, as the console says it after
    « « nom » refusé : » — None when the name is accepted."""
    refusal = file_name_refusal(name)
    return refusal.message if refusal else None


@dataclass(frozen=True)
class Problem:
    """Why a package cannot be deployed yet.

    ``code`` and ``params`` are what the console words, in its reader's
    language (plan ``dev/plan-console-bilingue.md``): the code names the
    sentence, ``params`` fills it — file names, lists of them, a size, and
    for ``untrusted`` the ``reason`` method A refuses the step for.
    ``message`` is the same sentence in French, kept for an older console
    and for whatever reads the API without one.

    ``blocks_uninstall``: whether it stands in the way of an uninstallation
    too. The agent reads the whole manifest before either step (deploy
    ParseManifest), so most do; a missing *install* step does not."""

    code: str
    message: str
    blocks_uninstall: bool = True
    params: dict[str, Any] = field(default_factory=dict)


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


# What makes msiexec remove a product instead of installing one: the switches
# /x and /uninstall, with either prefix msiexec takes and whatever is glued to
# them ("/x{code}"), and the property REMOVE= — "/i {code} REMOVE=ALL" is the
# documented other way to uninstall. Applied to a *piece* of an argument
# (``_pieces``). ASCII letters of either case spelled out, and no flag: a
# case-insensitive match folds by Unicode rules that differ between this
# module, the agent's Go and the signing script's .NET ("ı", "İ", "ſ"), and
# msiexec knows none of them. The agent (deploy.MsiExecRemoves) and the
# signing script ($MsiExecRemoval) apply the same rule; a test keeps the
# script's pattern equal to this one, and the three sides answer the same
# vectors (backend/tests/data/msiexec_removal_vectors.json).
MSIEXEC_REMOVAL = re.compile(
    r"^[/-]([xX]|[uU][nN][iI][nN][sS][tT][aA][lL][lL])|^[rR][eE][mM][oO][vV][eE]="
)


def _pieces(arg: str) -> Iterator[str]:
    """What msiexec may read as separate words in one argument: msiexec
    parses its command line itself, so an argument holding spaces — the agent
    passes it quoted — may still be read as several ("/qn /x {code}"). Split
    on whitespace, each piece rid of one pair of surrounding double quotes
    ('"/x"'). The rule as agreed also trims each piece, before and after its
    quotes: a piece cut on whitespace holds none, there is nothing to trim."""
    for piece in arg.split():
        if len(piece) >= 2 and piece[0] == piece[-1] == '"':
            piece = piece[1:-1]
        yield piece


def msiexec_removal(run: str | None, args: Sequence[str] | None) -> str | None:
    """The first argument that makes this msiexec step a removal, None when
    there is none — or when the step does not run msiexec: an executable's
    own /x is its business."""
    if run != MSIEXEC:
        return None
    for arg in args or ():
        if any(MSIEXEC_REMOVAL.search(piece) for piece in _pieces(arg)):
            return arg
    return None


def msiexec_removes(run: str | None, args: Sequence[str] | None) -> bool:
    """Whether a step runs msiexec with an argument that removes a product:
    an uninstallation, whatever step it is filed under. As an installation
    every poste refuses it (agent deploy.MsiExecRemoves, and
    deploy.MethodAStep under method A, which would otherwise rebuild it as
    ``/x {code}``)."""
    return msiexec_removal(run, args) is not None


INSTALL_REMOVES = (
    "L'installation lance une désinstallation (msiexec /x, /uninstall ou "
    "REMOVE=) : placez cette commande dans la désinstallation du paquet"
)


def by_product_code(package: Package) -> bool:
    """Whether the uninstallation is ``msiexec`` with an MSI product code among
    its arguments: what method A runs as ``/x {code}`` without downloading any
    file of the package (agent deploy.MethodAStep)."""
    return package.uninstall_run == MSIEXEC and any(
        PRODUCT_CODE.fullmatch(a) for a in package.uninstall_args or ()
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
                "install_missing",
                f"« {package.install_run} » n'est pas dans le paquet",
                params={"file": package.install_run},
            )
        )
    elif msiexec_removes(package.install_run, package.install_args):
        # Refused on write (packages._apply); a row written before that rule
        # may remain. The uninstallation is not concerned: the agent runs
        # only the step of the action it was sent.
        out.append(Problem("install_removes", INSTALL_REMOVES, blocks_uninstall=False))
    if (
        package.uninstall_run
        and package.uninstall_run != MSIEXEC
        and package.uninstall_run not in names
        # Said once when both steps name the same missing file.
        and package.uninstall_run != package.install_run
    ):
        out.append(
            Problem(
                "uninstall_missing",
                f"« {package.uninstall_run} » n'est pas dans le paquet",
                params={"file": package.uninstall_run},
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
                params={"groups": duplicates},
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
                params={"files": lost},
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
    refuses it, since the line it rebuilds is that uninstall."""
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


def _untrusted(package: Package, files: Sequence[PackageFile], action: str) -> Problem:
    """Why no poste would run this unsigned step, naming what stands in the
    way of method A: the file it runs, or the one beside it."""
    if runnable_somewhere(package, files, action, capped=False):
        # Method A in every respect but the size: the agent caps what an
        # unsigned manifest may have it download.
        gib = method_a_max_bytes() >> 30
        return Problem(
            "method_a_too_large",
            f"Plus de {gib} Gio de fichiers : sans signature de "
            "l'administrateur, aucun poste ne les téléchargera "
            "(plafond de la méthode A). Signez le paquet.",
            params={"gib": gib},
        )
    run = (
        package.uninstall_run if action == "uninstall" else package.install_run
    ) or ""
    run_file = next((f for f in files if f.name == run), None)
    loadable = sorted(
        (
            f.name
            for f in files
            if f.name != run and Path(f.name.lower()).suffix in LOADABLE_EXTENSIONS
        ),
        key=str.lower,
    )
    params: dict[str, Any] = {"file": run}
    if run == MSIEXEC and action == "uninstall":
        params["reason"] = "msiexec_uninstall"
        reason = (
            "sa désinstallation lance msiexec sans code produit {…} parmi ses "
            "arguments : la méthode A ne lance msiexec que pour « /x {code produit} »"
        )
    elif run == MSIEXEC:
        params["reason"] = "msiexec_install"
        reason = (
            "son installation lance msiexec : la méthode A ne lance qu'un "
            "exécutable (.exe) signé par un éditeur"
        )
    elif not run.lower().endswith(".exe"):
        params["reason"] = "not_exe"
        reason = (
            f"« {run} » n'est pas un exécutable (.exe) : la méthode A ne lance "
            "qu'un .exe signé par un éditeur"
        )
    elif run_file is None or not run_file.publisher_name:
        params["reason"] = "no_publisher"
        reason = (
            f"« {run} » ne porte pas de signature d'éditeur (Authenticode) : la "
            "méthode A ne le lance pas"
        )
    elif loadable:
        reason = (
            f"{_quoted(loadable)} "
            + ("sont" if len(loadable) > 1 else "est")
            + f" à côté de « {run} » : la méthode A refuse tout fichier que "
            "Windows pourrait charger ou lancer (.dll, .exe, .msi, scripts…) à "
            "côté de l'exécutable — retirez-"
            + ("les" if len(loadable) > 1 else "le")
            + " du paquet, ou"
        )
        return Problem(
            "untrusted",
            f"Paquet non signé, et {reason} signez-le : en l'état, aucun poste "
            "ne l'exécutera.",
            params={**params, "reason": "loadable", "files": loadable},
        )
    else:
        params["reason"] = "other"
        reason = "la méthode A ne le lance pas"
    return Problem(
        "untrusted",
        f"Paquet non signé, et {reason} : aucun poste ne l'exécutera. Signez le "
        "paquet.",
        params=params,
    )


def step_blockers(
    package: Package, files: Sequence[PackageFile], action: str = "install"
) -> list[Problem]:
    """What every poste would refuse this step for — what the command route
    answers 409 ``package.not_ready`` with, and what the package payload says
    as ``install_blockers``: the problems standing in the step's way, or else,
    when no poste would trust it, why (audit B30, U04). Empty when some poste
    could run it; always for a winget package, whose trust is winget's."""
    if package.kind != PackageKind.FILES:
        return []
    found = problems(package, files)
    if action == "uninstall":
        found = [p for p in found if p.blocks_uninstall]
        if not package.uninstall_run:
            found.append(Problem("no_uninstall", "Pas de désinstallation définie"))
    if found:
        return found
    if runnable_somewhere(package, files, action):
        return []
    return [_untrusted(package, files, action)]


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
        # ``or []`` throughout: a row may hold a JSON null where a list is
        # meant (written before the API refused it), read as an empty one —
        # which is how the agent reads an empty ``success_codes``: its own
        # defaults.
        "install": {
            "run": package.install_run,
            "args": list(package.install_args or []),
        }
        if package.install_run
        else None,
        "uninstall": {
            "run": package.uninstall_run,
            "args": list(package.uninstall_args or []),
        }
        if package.uninstall_run
        else None,
        "success_codes": list(package.success_codes or []),
    }
    # Indented and key-sorted for the administrator who opens it before
    # signing: it is a document somebody is meant to read.
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
