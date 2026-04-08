#!/usr/bin/env python3
"""Apply sql/schema.sql using DATABASE_URL (asyncpg). Use PGSSLMODE=disable for local Postgres without TLS."""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

# Repo root (parent of scripts/)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_SCHEMA = _ROOT / "sql" / "schema.sql"


def _split_sql(sql: str) -> list[str]:
    stripped = []
    for block in re.split(r";\s*", sql):
        block = block.strip()
        if not block:
            continue
        lines = [ln for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        if not lines:
            continue
        stripped.append("\n".join(lines).strip())
    return stripped


async def _main() -> int:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if url.startswith("sqlite:"):
        print("Use sqlite3 for sqlite URLs; this script targets Postgres.", file=sys.stderr)
        return 1

    if not _SCHEMA.is_file():
        print(f"Missing {_SCHEMA}", file=sys.stderr)
        return 1

    raw = _SCHEMA.read_text(encoding="utf-8")
    statements = _split_sql(raw)
    if not statements:
        print("No SQL statements found in schema file.", file=sys.stderr)
        return 1

    import asyncpg

    from persistent_store import _asyncpg_connect_kwargs

    conn = await asyncpg.connect(url, **_asyncpg_connect_kwargs(url))
    try:
        for stmt in statements:
            await conn.execute(stmt)
    finally:
        await conn.close()

    print(f"Applied {len(statements)} statement(s) from {_SCHEMA.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
