import os
import sys, pathlib

import importlib

import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _placeholder_environment(monkeypatch):
    """Provide non-zero placeholder IDs during tests when unset."""

    defaults = {
        "GUILD_ID": "1",
        "MENU_CHANNEL_ID": "10",
        "STATUS_CHANNEL_ID": "11",
        "UPLOAD_CHANNEL_ID": "12",
        "LAZARUS_CHANNEL_ID": "13",
        "CLEARANCE_REQUESTS_CHANNEL_ID": "14",
        "LEAD_NOTIFICATION_CHANNEL_ID": "15",
        "REPORT_REPLY_CHANNEL_ID": "16",
        "SECURITY_LOG_CHANNEL_ID": "17",
        "DISCORD_BOT_TOKEN": "placeholder-token",
        "LEVEL1_ROLE_ID": "100",
        "LEVEL2_ROLE_ID": "101",
        "LEVEL3_ROLE_ID": "102",
        "LEVEL4_ROLE_ID": "103",
        "LEVEL5_ROLE_ID": "104",
        "CLASSIFIED_ROLE_ID": "105",
        "ARCHIVIST_ROLE_ID": "200",
        "LEAD_ARCHIVIST_ROLE_ID": "201",
        "HIGH_COMMAND_ROLE_ID": "202",
        "TRAINEE_ROLE_ID": "203",
        "OWNER_ROLE_ID": "210",
        "XO_ROLE_ID": "211",
        "FLEET_ADMIRAL_ROLE_ID": "212",
        "CAPTAIN_ROLE_ID": "220",
        "VETERAN_OFFICER_ROLE_ID": "221",
        "OFFICER_ROLE_ID": "222",
        "SPECIALIST_ROLE_ID": "223",
        "SEAMAN_ROLE_ID": "224",
        "TRAINEE_RANK_ROLE_ID": "225",
    }
    for key, value in defaults.items():
        if not os.getenv(key):
            monkeypatch.setenv(key, value)

    # Ensure modules that cache configuration at import time pick up the
    # placeholder values before individual tests reload them again.
    import constants as _constants
    import server_config as _server_config
    import archive_status as _archive_status
    import operator_login as _operator_login

    importlib.reload(_constants)
    importlib.reload(_server_config)
    importlib.reload(_archive_status)
    importlib.reload(_operator_login)
    yield
