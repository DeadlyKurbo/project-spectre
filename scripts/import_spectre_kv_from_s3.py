#!/usr/bin/env python3
"""Copy JSON objects from an S3 bucket into spectre_kv (Postgres).

Requires AWS_* / S3_* env vars for boto3 (same as storage_spaces) and DATABASE_URL.
By default imports keys starting with --prefix (default: config/).

Example:
  DATABASE_URL=postgresql://... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \\
    S3_BUCKET=mybucket S3_ENDPOINT_URL=https://... python scripts/import_spectre_kv_from_s3.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _boto_client():
    import boto3
    from botocore.config import Config

    kw = {
        "service_name": "s3",
        "region_name": os.getenv("S3_REGION", "us-east-1"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "config": Config(s3={"addressing_style": "virtual"}),
    }
    endpoint = (os.getenv("S3_ENDPOINT_URL") or "").strip()
    if endpoint:
        kw["endpoint_url"] = endpoint
    return boto3.client(**kw)


def _normalize_prefix(root_prefix: str, prefix: str) -> str:
    root = root_prefix.strip().strip("/")
    p = prefix.strip().strip("/")
    if not root:
        return f"{p}/" if p and not p.endswith("/") else (p or "")
    if not p:
        return f"{root}/"
    return f"{root}/{p}/" if not p.endswith("/") else f"{root}/{p}"


def _storage_key_for_kv(object_key: str, root_prefix: str) -> str:
    """Strip S3_ROOT_PREFIX so keys match persistent_store paths (e.g. config/config.json)."""

    r = root_prefix.strip().strip("/")
    k = object_key.strip().strip("/")
    if not r:
        return k
    if k == r:
        return ""
    if k.startswith(r + "/"):
        return k[len(r) + 1 :]
    return k


async def _import_keys(
    *,
    prefix: str,
    dry_run: bool,
    limit: int | None,
) -> int:
    bucket = (os.getenv("S3_BUCKET") or "").strip()
    if not bucket:
        print("S3_BUCKET is required.", file=sys.stderr)
        return 1
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url or db_url.startswith("sqlite:"):
        print("DATABASE_URL must be a Postgres URL.", file=sys.stderr)
        return 1

    root_prefix = (os.getenv("S3_ROOT_PREFIX") or "").strip().strip("/")
    full_prefix = _normalize_prefix(root_prefix, prefix)

    client = _boto_client()
    paginator = client.get_paginator("list_objects_v2")

    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=full_prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if not key or key.endswith("/") or key.endswith(".keep"):
                continue
            if not key.lower().endswith(".json"):
                continue
            keys.append(key)
            if limit is not None and len(keys) >= limit:
                break
        if limit is not None and len(keys) >= limit:
            break

    if not keys:
        print(f"No JSON keys under prefix {full_prefix!r}.")
        return 0

    import asyncpg

    from persistent_store import RailwayPersistenceBackend, _asyncpg_connect_kwargs

    RailwayPersistenceBackend(db_url)  # ensure spectre_kv exists

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = await asyncpg.connect(db_url, **_asyncpg_connect_kwargs(db_url))
    imported = 0
    try:
        for key in keys:
            storage_key = _storage_key_for_kv(key, root_prefix)
            if not storage_key:
                print(f"Skip (empty key after prefix strip): {key}", file=sys.stderr)
                continue
            obj = client.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            try:
                parsed = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                print(f"Skip (invalid JSON): {key} ({exc})", file=sys.stderr)
                continue
            payload_json = json.dumps(parsed, ensure_ascii=False, indent=2)
            if dry_run:
                print(f"would import {storage_key} <= {key} ({len(payload_json)} chars)")
                imported += 1
                continue
            await conn.execute(
                """
                INSERT INTO spectre_kv(storage_key, value_json, updated_at)
                VALUES ($1, $2, $3)
                ON CONFLICT(storage_key)
                DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at
                """,
                storage_key,
                payload_json,
                now,
            )
            imported += 1
            print(f"imported {storage_key}")
    finally:
        await conn.close()

    print(f"Done. {'Would import' if dry_run else 'Imported'} {imported} key(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix",
        default="config/",
        help="Key prefix inside the bucket (after S3_ROOT_PREFIX if set).",
    )
    parser.add_argument("--dry-run", action="store_true", help="List actions without writing to Postgres.")
    parser.add_argument("--limit", type=int, default=None, help="Max number of keys to process.")
    args = parser.parse_args()
    return asyncio.run(
        _import_keys(prefix=args.prefix, dry_run=args.dry_run, limit=args.limit)
    )


if __name__ == "__main__":
    raise SystemExit(main())
