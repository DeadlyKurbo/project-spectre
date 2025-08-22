from datetime import datetime, UTC, timedelta


def test_generate_status_message_counts(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import main

    fixed_now = datetime(2025, 1, 1, tzinfo=UTC)
    earlier = fixed_now - timedelta(minutes=30)
    older = fixed_now - timedelta(hours=2)
    logs = "\n".join(
        [
            f"{older.isoformat()} 📄 old_user accessed `old/file.txt`.",
            f"{earlier.isoformat()} 📄 user accessed `intel/file.txt`.",
            f"{earlier.isoformat()} ✉️ user requested clearance for `intel/file.txt`.",
            f"{earlier.isoformat()} ✅ approver granted user access to `intel/file.txt`.",
            f"{earlier.isoformat()} ❌ approver denied user access to `intel/file2.txt`.",
            f"{earlier.isoformat()} ✏️ user edited `intel/file.txt`.",
        ]
    )
    monkeypatch.setattr(main, "read_text", lambda _: logs)
    monkeypatch.setattr(main, "_count_all_files", lambda prefix: 16)
    monkeypatch.setattr(main, "NEXT_BACKUP_TS", fixed_now + timedelta(hours=2))
    monkeypatch.setattr(main, "SESSION_ID", "ABC123")
    monkeypatch.setattr(main, "get_build_version", lambda: "vTest")
    monkeypatch.setattr(main.random, "choice", lambda seq: seq[0])

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(main, "datetime", FixedDateTime)
    msg = main._generate_status_message()
    assert "File accesses: 2 (📄 reads: 1 • ✏️ edits: 1)" in msg
    assert "Requests: 1 (approved: 1 • denied: 1 • pending: 0)" in msg
    assert "🏆 @user (3 actions)" in msg
    assert "SID: ABC123 • Build: vTest" in msg
    assert "📦 Next backup scheduled" in msg

