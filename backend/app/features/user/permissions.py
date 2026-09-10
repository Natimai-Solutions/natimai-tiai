"""Authorization model: permissions as (resource, action) pairs, held by groups.

Routes ask for a capability (``require_permission(Resource.MACHINE, Action.READ)``)
rather than checking who the caller is. What a caller may do is the union of
the permissions of the groups they belong to (``crud.user_permissions``), and
those live in the database: an administrator composes a group in the console —
"may run the everyday commands but not touch the accounts" — instead of picking
one of two roles baked in here.

Three groups are built in (``BuiltinGroup``) so a fresh install and a migrated
one both start with something sensible. Only one of them is special: the
administrators' group holds every permission implicitly, catalogue additions
included, so a new resource never has to be granted to it by hand.
"""

import enum


class Resource(enum.StrEnum):
    """Protected resource families."""

    MACHINE = "machine"
    THREAT = "threat"
    COMMAND = "command"
    # The commands that can cost somebody their work or change the poste for
    # good — a shutdown, an update install, a DISM repair — as opposed to a
    # scan or a cache flush. Its own resource rather than a flag on COMMAND so
    # that the everyday catalogue can be handed to a group without the
    # dangerous half. Which types are which: ``command.models.RISKY_COMMAND_TYPES``.
    RISKY_COMMAND = "risky_command"
    # Buildings and rooms — where the postes are, as the console organises it.
    ROOM = "room"
    # The journal of a poste: interventions recorded by hand.
    INTERVENTION = "intervention"
    # Verification requests: "go and look at this poste".
    CHECK = "check"
    USER = "user"
    # The audit log. Admin material like USER: who did what to the parc's
    # accounts and tokens.
    AUDIT = "audit"


class Action(enum.StrEnum):
    """Operations on a resource."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"  # e.g. dispatch a remote command


# The permissions that exist, as the console's grid offers them. A pair absent
# from this list is refused on a group write: a typo in a request must not
# create a permission nothing ever checks for.
PERMISSION_CATALOGUE: tuple[tuple[Resource, Action], ...] = (
    (Resource.MACHINE, Action.READ),
    (Resource.MACHINE, Action.WRITE),
    (Resource.THREAT, Action.READ),
    (Resource.COMMAND, Action.READ),
    (Resource.COMMAND, Action.EXECUTE),
    (Resource.RISKY_COMMAND, Action.EXECUTE),
    (Resource.ROOM, Action.READ),
    (Resource.ROOM, Action.WRITE),
    (Resource.INTERVENTION, Action.READ),
    (Resource.INTERVENTION, Action.WRITE),
    (Resource.CHECK, Action.READ),
    (Resource.CHECK, Action.WRITE),
    (Resource.USER, Action.READ),
    (Resource.USER, Action.WRITE),
    (Resource.AUDIT, Action.READ),
)


def permission_key(resource: Resource | str, action: Action | str) -> str:
    """The stored form of a permission: ``"machine:read"``."""
    return f"{resource}:{action}"


ALL_PERMISSIONS: frozenset[str] = frozenset(
    permission_key(r, a) for r, a in PERMISSION_CATALOGUE
)

# What a read-only account is for: the supervision screens, and nothing that
# changes anything.
_SUPERVISION_READ = frozenset(
    {
        permission_key(Resource.MACHINE, Action.READ),
        permission_key(Resource.THREAT, Action.READ),
        permission_key(Resource.COMMAND, Action.READ),
        permission_key(Resource.ROOM, Action.READ),
        permission_key(Resource.INTERVENTION, Action.READ),
        permission_key(Resource.CHECK, Action.READ),
    }
)


class BuiltinGroup(enum.StrEnum):
    """The groups every installation has. Their key is stable; their name and,
    except for the administrators, their permissions are the operator's to
    change."""

    ADMIN = "admin"
    READONLY = "readonly"
    TECHNICIAN = "technician"


# key → (name, description, default permissions). The administrators' set is
# empty here because it is implicit (see module docstring).
BUILTIN_GROUP_DEFAULTS: dict[BuiltinGroup, tuple[str, str, frozenset[str]]] = {
    BuiltinGroup.ADMIN: (
        "Administrateurs",
        "Tous les droits, y compris ceux des ressources à venir.",
        frozenset(),
    ),
    BuiltinGroup.READONLY: (
        "Lecture seule",
        "Consulte le parc sans rien pouvoir y changer.",
        _SUPERVISION_READ,
    ),
    BuiltinGroup.TECHNICIAN: (
        "Techniciens",
        "Consulte le parc et exécute les commandes, courantes et à risque.",
        _SUPERVISION_READ
        | {
            permission_key(Resource.COMMAND, Action.EXECUTE),
            permission_key(Resource.RISKY_COMMAND, Action.EXECUTE),
            permission_key(Resource.INTERVENTION, Action.WRITE),
            permission_key(Resource.CHECK, Action.WRITE),
        },
    ),
}


def has_permission(
    permissions: frozenset[str] | set[str], resource: str, action: str
) -> bool:
    """Whether a permission set — a user's, as ``crud.user_permissions`` builds
    it — grants ``(resource, action)``."""
    return permission_key(resource, action) in permissions
