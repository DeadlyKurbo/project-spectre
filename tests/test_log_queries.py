import importlib
import asyncio


def setup_main(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    asyncio.set_event_loop(asyncio.new_event_loop())
    main = importlib.reload(importlib.import_module("main"))
    log_path = tmp_path / "actions.log"
    main.LOG_FILE = str(log_path)
    return main, log_path


def test_get_user_logs(monkeypatch, tmp_path):
    main, log_path = setup_main(monkeypatch, tmp_path)
    log_path.write_text("""t1 Alice did a\nt2 Bob did b\nt3 Alice did c\n""")
    assert main.get_user_logs("Alice") == ["t1 Alice did a", "t3 Alice did c"]


def test_get_file_logs(monkeypatch, tmp_path):
    main, log_path = setup_main(monkeypatch, tmp_path)
    log_path.write_text(
        """t1 user accessed The_Delta_Lady\nt2 user edited Other_File\nt3 user viewed The_Delta_Lady\n"""
    )
    assert main.get_file_logs("The_Delta_Lady") == [
        "t1 user accessed The_Delta_Lady",
        "t3 user viewed The_Delta_Lady",
    ]
