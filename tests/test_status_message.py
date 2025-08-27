from datetime import datetime, UTC, timedelta


def test_generate_status_message_counts(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import main

    fixed_now = datetime(2025, 1, 1, tzinfo=UTC)
    earlier = fixed_now - timedelta(minutes=30)
    older = fixed_now - timedelta(days=2)
    logs = "\n".join(
        [
            f"{older.isoformat()}  @old_user accessed `old/file.txt`.",
            f"{earlier.isoformat()}  @user accessed `intel/file.txt`.",
            f"{earlier.isoformat()}  @user requested clearance for `intel/file.txt`.",
            f"{earlier.isoformat()}  @approver granted @user access to `intel/file.txt`.",
            f"{earlier.isoformat()}  @approver denied @user access to `intel/file2.txt`.",
            f"{earlier.isoformat()}  @user edited `intel/file.txt`.",
        ]
    )
    monkeypatch.setattr(main, "read_text", lambda _: logs)
    monkeypatch.setattr(main, "_count_all_files", lambda prefix: 16)
    monkeypatch.setattr(main, "NEXT_BACKUP_TS", fixed_now + timedelta(hours=2))
    monkeypatch.setattr(main, "LAST_BACKUP_TS", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "START_TIME", fixed_now - timedelta(hours=164))
    monkeypatch.setattr(main, "SESSION_ID", "ABC123")
    monkeypatch.setattr(main, "get_build_version", lambda: "vTest")
    monkeypatch.setattr(main.random, "choice", lambda seq: seq[0])

    class DummyMember:
        mention = "<@42>"

    class DummyGuild:
        def get_member_named(self, name):
            return DummyMember() if name == "user" else None

    class DummyBot:
        latency = 0.123

        def is_ready(self):
            return True

        def get_guild(self, gid):
            return DummyGuild()

    monkeypatch.setattr(main, "bot", DummyBot())

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(main, "datetime", FixedDateTime)
    msg = main._generate_status_message()
    assert " **System Node Health**" in msg
    assert "Node Alpha:  ONLINE (Nominal)" in msg
    assert " Bot ping: 123ms" in msg
    assert " Connection: Stable" in msg
    assert " Avg response: 143ms" in msg
    assert "Backups: Next" in msg and "Last: 23:00Z" in msg
    assert " **Archive Overview**" in msg
    assert "Integrity: All 16 files verified • 0 mismatches" in msg
    assert " **Access Breakdown (24h)**" in msg
    assert "2 accesses (1 read • 1 edit)" in msg
    assert " Approved: 1" in msg
    assert " Denied: 1" in msg
    assert " Pending: 0" in msg
    assert " **Top Archivist (24h)**" in msg
    assert "<@42> (3 actions)" in msg
    assert " intel/file.txt — approved by @approver" in msg
    assert "Node Cluster: BOREAL-07" in msg
    assert "Build: vTest" in msg and "SID: ABC123" in msg


def test_status_message_ignores_system_logs(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import main

    fixed_now = datetime(2025, 1, 1, tzinfo=UTC)
    earlier = fixed_now - timedelta(minutes=30)
    logs = f"{earlier.isoformat()}  Backup saved to `foo.json`.\n"
    monkeypatch.setattr(main, "read_text", lambda _: logs)
    monkeypatch.setattr(main, "_count_all_files", lambda prefix: 0)
    monkeypatch.setattr(main, "NEXT_BACKUP_TS", fixed_now + timedelta(hours=2))
    monkeypatch.setattr(main, "LAST_BACKUP_TS", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "START_TIME", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "SESSION_ID", "ABC123")
    monkeypatch.setattr(main, "get_build_version", lambda: "vTest")
    monkeypatch.setattr(main.random, "choice", lambda seq: seq[0])

    class DummyBot:
        latency = 0.0

        def is_ready(self):
            return True

        def get_guild(self, gid):
            return None

    monkeypatch.setattr(main, "bot", DummyBot())

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(main, "datetime", FixedDateTime)

    msg = main._generate_status_message()
    assert " **Top Archivist (24h)**" in msg
    assert "N/A (0 actions)" in msg


def test_status_message_excludes_error_reports(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import main

    fixed_now = datetime(2025, 1, 1, tzinfo=UTC)
    earlier = fixed_now - timedelta(minutes=30)
    logs = "\n".join(
        [
            f"{earlier.isoformat()}  @user reported error 'bad' on `intel/file`: oops",
            f"{earlier.isoformat()}  @user accessed `intel/file`.",
        ]
    )
    monkeypatch.setattr(main, "read_text", lambda _: logs)
    monkeypatch.setattr(main, "_count_all_files", lambda prefix: 1)
    monkeypatch.setattr(main, "NEXT_BACKUP_TS", fixed_now + timedelta(hours=2))
    monkeypatch.setattr(main, "LAST_BACKUP_TS", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "START_TIME", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "SESSION_ID", "ABC123")
    monkeypatch.setattr(main, "get_build_version", lambda: "vTest")
    monkeypatch.setattr(main.random, "choice", lambda seq: seq[0])

    class DummyBot:
        latency = 0.0

        def is_ready(self):
            return True

        def get_guild(self, gid):
            return None

    monkeypatch.setattr(main, "bot", DummyBot())

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(main, "datetime", FixedDateTime)

    msg = main._generate_status_message()
    assert "reported error" not in msg
    assert "intel/file" in msg


def test_duplicate_request_resolved_by_denial(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import main

    fixed_now = datetime(2025, 1, 1, tzinfo=UTC)
    earlier = fixed_now - timedelta(minutes=30)
    logs = "\n".join(
        [
            f"{earlier.isoformat()}  @user requested clearance for `intel/file.txt`.",
            f"{earlier.isoformat()}  @user requested clearance for `intel/file.txt`.",
            f"{earlier.isoformat()}  @approver denied @user access to `intel/file.txt`.",
        ]
    )
    monkeypatch.setattr(main, "read_text", lambda _: logs)
    monkeypatch.setattr(main, "_count_all_files", lambda prefix: 1)
    monkeypatch.setattr(main, "NEXT_BACKUP_TS", fixed_now + timedelta(hours=2))
    monkeypatch.setattr(main, "LAST_BACKUP_TS", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "START_TIME", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "SESSION_ID", "ABC123")
    monkeypatch.setattr(main, "get_build_version", lambda: "vTest")
    monkeypatch.setattr(main.random, "choice", lambda seq: seq[0])

    class DummyBot:
        latency = 0.0

        def is_ready(self):
            return True

        def get_guild(self, gid):
            return None

    monkeypatch.setattr(main, "bot", DummyBot())

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(main, "datetime", FixedDateTime)

    msg = main._generate_status_message()
    assert " Denied: 1" in msg
    assert " Pending: 0" in msg


def test_status_message_excludes_trainee_submissions(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import main

    fixed_now = datetime(2025, 1, 1, tzinfo=UTC)
    earlier = fixed_now - timedelta(minutes=30)
    logs = "\n".join(
        [
            f"{earlier.isoformat()}  @user approved trainee submission 42.",
            f"{earlier.isoformat()}  @user denied trainee submission 42: nope",
            f"{earlier.isoformat()}  @user accessed `intel/file.txt`.",
        ]
    )
    monkeypatch.setattr(main, "read_text", lambda _: logs)
    monkeypatch.setattr(main, "_count_all_files", lambda prefix: 1)
    monkeypatch.setattr(main, "NEXT_BACKUP_TS", fixed_now + timedelta(hours=2))
    monkeypatch.setattr(main, "LAST_BACKUP_TS", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "START_TIME", fixed_now - timedelta(hours=1))
    monkeypatch.setattr(main, "SESSION_ID", "ABC123")
    monkeypatch.setattr(main, "get_build_version", lambda: "vTest")
    monkeypatch.setattr(main.random, "choice", lambda seq: seq[0])

    class DummyBot:
        latency = 0.0

        def is_ready(self):
            return True

        def get_guild(self, gid):
            return None

    monkeypatch.setattr(main, "bot", DummyBot())

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(main, "datetime", FixedDateTime)

    msg = main._generate_status_message()
    assert "trainee submission" not in msg
    assert "intel/file.txt" in msg

