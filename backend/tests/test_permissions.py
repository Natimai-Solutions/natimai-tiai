from app.features.user.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_GROUP_DEFAULTS,
    PERMISSION_CATALOGUE,
    Action,
    BuiltinGroup,
    Resource,
    has_permission,
    permission_key,
)


def test_permission_key_is_resource_colon_action():
    assert permission_key(Resource.MACHINE, Action.READ) == "machine:read"
    assert permission_key("risky_command", "execute") == "risky_command:execute"


def test_catalogue_has_no_duplicates_and_matches_all_permissions():
    keys = [permission_key(r, a) for r, a in PERMISSION_CATALOGUE]
    assert len(keys) == len(set(keys))
    assert set(keys) == ALL_PERMISSIONS


def test_builtin_defaults_only_grant_catalogue_permissions():
    """A default outside the catalogue would be a permission no route checks."""
    for _name, _description, permissions in BUILTIN_GROUP_DEFAULTS.values():
        assert permissions <= ALL_PERMISSIONS


def test_admin_defaults_are_empty_because_implicit():
    assert BUILTIN_GROUP_DEFAULTS[BuiltinGroup.ADMIN][2] == frozenset()


def test_readonly_can_read_supervision_resources_only():
    perms = BUILTIN_GROUP_DEFAULTS[BuiltinGroup.READONLY][2]
    for resource in (Resource.MACHINE, Resource.THREAT, Resource.COMMAND):
        assert has_permission(perms, resource, Action.READ)
    assert not has_permission(perms, Resource.MACHINE, Action.WRITE)
    assert not has_permission(perms, Resource.COMMAND, Action.EXECUTE)
    assert not has_permission(perms, Resource.USER, Action.READ)


def test_technician_runs_commands_but_manages_nothing():
    perms = BUILTIN_GROUP_DEFAULTS[BuiltinGroup.TECHNICIAN][2]
    assert has_permission(perms, Resource.COMMAND, Action.EXECUTE)
    assert has_permission(perms, Resource.RISKY_COMMAND, Action.EXECUTE)
    assert not has_permission(perms, Resource.MACHINE, Action.WRITE)
    assert not has_permission(perms, Resource.USER, Action.READ)


def test_empty_set_is_denied_everything():
    for resource in Resource:
        for action in Action:
            assert not has_permission(frozenset(), resource, action)


def test_risky_command_types_are_a_subset_of_the_catalogue():
    from app.features.command.models import RISKY_COMMAND_TYPES, CommandType

    assert RISKY_COMMAND_TYPES <= set(CommandType)
    assert CommandType.REBOOT in RISKY_COMMAND_TYPES
    assert CommandType.QUICK_SCAN not in RISKY_COMMAND_TYPES
