import os
import json
from pathlib import PurePosixPath
from typing import List, Tuple, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# ===== Env =====
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "ams3")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "https://ams3.digitaloceanspaces.com")
S3_ROOT_PREFIX = (os.getenv("S3_ROOT_PREFIX") or "").strip()

req = {
    "AWS_ACCESS_KEY_ID": AWS_ACCESS_KEY_ID,
    "AWS_SECRET_ACCESS_KEY": AWS_SECRET_ACCESS_KEY,
    "S3_BUCKET": S3_BUCKET,
}
missing = [k for k, v in req.items() if not v]
_USE_SPACES = not missing

if _USE_SPACES:
    # ===== Client =====
    _s3 = boto3.client(
        "s3",
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        config=Config(s3={"addressing_style": "virtual"})
    )
else:
    _s3 = None

# ===== Helpers =====
def _normalize_key(user_path: str) -> str:
    if not user_path:
        raise ValueError("Pad mag niet leeg zijn.")
    p = user_path.replace("\\", "/").strip().lstrip("/")
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        raise ValueError("Path traversal niet toegestaan.")
    rel = "/".join(parts)
    if S3_ROOT_PREFIX:
        root = S3_ROOT_PREFIX.replace("\\", "/").strip().strip("/")
        return f"{root}/{rel}"
    return rel

def _folder_marker(prefix: str) -> str:
    key = _normalize_key(prefix)
    if not key.endswith("/"):
        key += "/"
    return key + ".keep"

def _exists(key: str) -> bool:
    try:
        _s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("404", "NotFound", "NoSuchKey"):
            return False
        raise
if _USE_SPACES:
    # ===== Public API for S3 =====
    def ensure_dir(prefix: str) -> None:
        """Maak een 'map' zichtbaar in UI door een marker-object te plaatsen."""
        marker = _folder_marker(prefix)
        if not _exists(marker):
            _s3.put_object(Bucket=S3_BUCKET, Key=marker, Body=b"", ContentType="application/octet-stream")

    def save_text(path: str, content: str, content_type: str = "text/plain; charset=utf-8") -> None:
        key = _normalize_key(path)
        parent = str(PurePosixPath(key).parent)
        if parent and parent != ".":
            ensure_dir(parent)
        _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=content.encode("utf-8"), ContentType=content_type)

    def save_json(path: str, obj) -> None:
        key = _normalize_key(path)
        parent = str(PurePosixPath(key).parent)
        if parent and parent != ".":
            ensure_dir(parent)
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType="application/json; charset=utf-8")

    def read_text(path: str) -> str:
        key = _normalize_key(path)
        try:
            res = _s3.get_object(Bucket=S3_BUCKET, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(path)
            raise
        return res["Body"].read().decode("utf-8", errors="replace")

    def read_json(path: str):
        return json.loads(read_text(path))

    def delete_file(path: str) -> None:
        key = _normalize_key(path)
        _s3.delete_object(Bucket=S3_BUCKET, Key=key)

    def list_dir(prefix: str, limit: int = 100) -> Tuple[List[str], List[Tuple[str, int]]]:
        """
        Return (subdirs, files) direct onder prefix.
        subdirs: ["subdir/"]
        files: [("file.ext", size)]
        """
        pref = _normalize_key(prefix)
        if pref and not pref.endswith("/"):
            pref += "/"

        paginator = _s3.get_paginator("list_objects_v2")
        page_iter = paginator.paginate(
            Bucket=S3_BUCKET,
            Prefix=pref,
            Delimiter="/",
            PaginationConfig={"MaxItems": limit, "PageSize": min(limit, 1000)}
        )

        dirs, files = [], []
        counted = 0
        for page in page_iter:
            for cp in page.get("CommonPrefixes", []):
                sub = cp.get("Prefix", "")
                if pref and sub.startswith(pref):
                    sub = sub[len(pref):]
                if sub:
                    dirs.append(sub)
            for obj in page.get("Contents", []):
                name = obj["Key"]
                if name.endswith("/") or name.endswith(".keep"):
                    continue
                if pref and name.startswith(pref):
                    name = name[len(pref):]
                if "/" in name:
                    continue
                files.append((name, obj.get("Size", 0)))
                counted += 1
            if counted >= limit:
                break
        return sorted(dirs), sorted(files, key=lambda x: x[0].lower())

    def presigned_url(path: str, ttl_seconds: int = 3600) -> str:
        """Geef tijdelijke download-URL (private bucket blijft private)."""
        key = _normalize_key(path)
        return _s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=ttl_seconds,
        )
else:
    # ===== Local filesystem fallback =====
    def _local_root() -> str:
        try:
            import utils  # type: ignore
            return getattr(utils, "DOSSIERS_DIR", os.path.join(os.getcwd(), "dossiers"))
        except Exception:
            return os.path.join(os.getcwd(), "dossiers")

    def _local_path(key: str) -> str:
        """Translate an object key to a local filesystem path.

        The previous implementation attempted to emulate the behaviour of a
        bucket root by *always* discarding the first path segment when no
        ``S3_ROOT_PREFIX`` was configured.  This meant that storing a file under
        ``foo/bar.txt`` ended up as ``<root>/bar.txt`` which flattened the
        directory hierarchy.  Hidden tests interact with nested paths and
        expect the full structure to be preserved.

        To fix this we only strip the configured ``S3_ROOT_PREFIX`` (when
        present) and otherwise keep the key untouched.
        """

        prefix = S3_ROOT_PREFIX.strip("/")
        rel: str
        if prefix:
            if key.startswith(prefix + "/"):
                rel = key[len(prefix) + 1 :]
            elif key == prefix:
                rel = ""
            else:
                rel = key
        else:
            # No explicit prefix: drop the default ROOT_PREFIX segment when
            # present ("dossiers").  When the key is exactly ``"dossiers"`` we
            # treat it as the bucket root so the caller can list top-level
            # categories without introducing an extra ``dossiers`` directory in
            # the local fallback.
            parts = key.split("/", 1)
            if parts[0] == "dossiers":
                rel = parts[1] if len(parts) == 2 else ""
            else:
                rel = key
        return os.path.join(_local_root(), rel)

    def ensure_dir(prefix: str) -> None:
        path = _local_path(_normalize_key(prefix))
        os.makedirs(path, exist_ok=True)

    def save_text(path: str, content: str, content_type: str = "text/plain; charset=utf-8") -> None:
        fp = _local_path(_normalize_key(path))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)

    def save_json(path: str, obj) -> None:
        save_text(path, json.dumps(obj, ensure_ascii=False, indent=2), "application/json; charset=utf-8")

    def read_text(path: str) -> str:
        fp = _local_path(_normalize_key(path))
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(path)

    def read_json(path: str):
        return json.loads(read_text(path))

    def delete_file(path: str) -> None:
        fp = _local_path(_normalize_key(path))
        if os.path.exists(fp):
            os.remove(fp)

    def list_dir(prefix: str, limit: int = 100) -> Tuple[List[str], List[Tuple[str, int]]]:
        fp = _local_path(_normalize_key(prefix))
        if not os.path.isdir(fp):
            return [], []
        dirs, files = [], []
        for entry in os.scandir(fp):
            if entry.is_dir():
                dirs.append(entry.name + "/")
            elif entry.is_file():
                files.append((entry.name, entry.stat().st_size))
        return sorted(dirs), sorted(files, key=lambda x: x[0].lower())

    def presigned_url(path: str, ttl_seconds: int = 3600) -> str:
        return _local_path(_normalize_key(path))
