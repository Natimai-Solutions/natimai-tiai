from app.features.user.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_GROUP_DEFAULTS,
    PERMISSION_CATALOGUE,
    Action,
    Authority,
    BuiltinGroup,
    Resource,
    escalation,
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


# --- No escalation ------------------------------------------------------------

_TECH = frozenset({"machine:read", "user:read", "user:write", "command:execute"})


def _authority(*permissions: str, admin: bool = False) -> Authority:
    return Authority(is_admin=admin, permissions=frozenset(permissions))


def test_an_administrator_reaches_everything():
    admin = _authority(admin=True)
    assert escalation(admin, _authority(*ALL_PERMISSIONS, admin=True)) is None


def test_a_subset_of_ones_own_rights_is_within_reach():
    actor = _authority(*_TECH)
    assert escalation(actor, _authority("machine:read", "user:read")) is None
    assert escalation(actor, _authority(*_TECH)) is None
    assert escalation(actor, _authority()) is None


def test_a_permission_one_lacks_is_out_of_reach_and_named():
    found = escalation(
        _authority(*_TECH), _authority("machine:read", "risky_command:execute")
    )
    assert found is not None
    assert found.missing == {"risky_command:execute"}
    assert not found.admin


def test_the_administrators_group_is_out_of_reach_even_with_every_permission():
    """A composed group may grant the whole catalogue; only the administrators'
    group grants tomorrow's permissions too — and makes administrators."""
    found = escalation(_authority(*ALL_PERMISSIONS), _authority(admin=True))
    assert found is not None
    assert found.admin
    assert found.missing == frozenset()


def test_authority_union_adds_permissions_and_admin_status():
    union = Authority.union(
        [_authority("machine:read"), _authority("user:read", admin=True)]
    )
    assert union.is_admin
    assert union.permissions == {"machine:read", "user:read"}
    assert Authority.union([]) == _authority()
