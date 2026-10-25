import pytest

import archive_index
import server_config

GUILD_ID = 4242
LEVEL_ROLES = {1: 101, 2: 202, 3: 303, 4: 404, 5: 505, 6: 606}
CUSTOM_ROLE = 999


def _config(strict=None):
    clearance = {"levels": {str(level): {"roles": [str(role)]} for level, role in LEVEL_ROLES.items()}}
    if strict is not None:
        clearance["strict_levels"] = strict
    return server_config._apply_dashboard_overrides({"clearance": clearance})


@pytest.fixture
def use_config(monkeypatch):
    def apply(strict=None):
        cfg = _config(strict)
        monkeypatch.setattr(server_config, "get_server_config", lambda gid: cfg)

    return apply


def test_higher_level_opens_lower_level_files_by_default(use_config):
    use_config()

    assert server_config.clearance_levels_stack(GUILD_ID)
    for file_level in (1, 2, 3, 4):
        assert server_config.roles_have_clearance({404}, {LEVEL_ROLES[file_level]}, GUILD_ID)
    for file_level in (5, 6):
        assert not server_config.roles_have_clearance({404}, {LEVEL_ROLES[file_level]}, GUILD_ID)


def test_strict_levels_only_open_their_own_files(use_config):
    use_config(strict=True)

    assert not server_config.clearance_levels_stack(GUILD_ID)
    assert server_config.roles_have_clearance({404}, {404}, GUILD_ID)
    assert not server_config.roles_have_clearance({404}, {101}, GUILD_ID)
    assert not server_config.roles_have_clearance({606}, {101}, GUILD_ID)


def test_strict_levels_must_be_exactly_true(use_config):
    use_config(strict="yes")

    assert server_config.clearance_levels_stack(GUILD_ID)


def test_roles_outside_levels_need_a_direct_match(use_config):
    use_config()

    # A file locked to a custom role is not opened by clearance levels.
    assert not server_config.roles_have_clearance({606}, {CUSTOM_ROLE}, GUILD_ID)
    assert server_config.roles_have_clearance({CUSTOM_ROLE}, {CUSTOM_ROLE}, GUILD_ID)
    # A custom role alone carries no clearance level.
    assert not server_config.roles_have_clearance({CUSTOM_ROLE}, {101}, GUILD_ID)
    # Open files are left to the callers' own rules.
    assert not server_config.roles_have_clearance({606}, set(), GUILD_ID)


def test_file_level_is_its_lowest_locked_level(use_config):
    use_config()

    assert server_config.roles_have_clearance({202}, {101, 606}, GUILD_ID)
    assert not server_config.roles_have_clearance({202}, {303, 606}, GUILD_ID)


def _resolver(levels_stack):
    return archive_index.AccessResolver(
        table={},
        role_levels={role: level for level, role in LEVEL_ROLES.items()},
        level_names={},
        level_roles={level: {role} for level, role in LEVEL_ROLES.items()},
        levels_stack=levels_stack,
    )


def test_website_resolver_stacks_levels():
    resolver = _resolver(levels_stack=True)

    assert resolver.allows({404}, {101})
    assert resolver.allows({404}, {404})
    assert not resolver.allows({404}, {505})
    assert not resolver.allows({606}, {CUSTOM_ROLE})
    assert resolver.allows({CUSTOM_ROLE}, {CUSTOM_ROLE})


def test_website_resolver_strict_levels():
    resolver = _resolver(levels_stack=False)

    assert resolver.allows({404}, {404})
    assert not resolver.allows({404}, {101})


def test_build_access_resolver_reads_strict_setting(use_config, monkeypatch):
    monkeypatch.setattr(archive_index.acl, "load_clearance", lambda gid: {})

    use_config()
    assert archive_index.build_access_resolver(GUILD_ID).levels_stack

    use_config(strict=True)
    assert not archive_index.build_access_resolver(GUILD_ID).levels_stack
