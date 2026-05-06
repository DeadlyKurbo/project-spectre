from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_moderation_schema_contains_required_tables():
    schema = (ROOT / "sql" / "moderation_schema.sql").read_text(encoding="utf-8")
    required = (
        "moderated_subjects",
        "user_identities",
        "moderation_cases",
        "case_events",
        "sanctions",
        "enforcement_actions",
        "appeals",
        "audit_events",
        "moderation_policies",
    )
    for table_name in required:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema


def test_migration_bootstrap_references_schema_file():
    migration = (ROOT / "sql" / "migrations" / "001_moderation_schema.sql").read_text(encoding="utf-8")
    assert "sql/moderation_schema.sql" in migration
