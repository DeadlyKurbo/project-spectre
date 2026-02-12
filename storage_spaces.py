import os
import json
import time
import hashlib
import mimetypes
from pathlib import PurePosixPath
from typing import IO, List, Tuple, Optional
import shutil
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

# ===== Env =====
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_REGION = os.getenv("S3_REGION", "ams3")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "https://ams3.digitaloceanspaces.com")
S3_ROOT_PREFIX = (os.getenv("S3_ROOT_PREFIX") or "").strip()
FORCE_LOCAL_STORAGE = os.getenv("FORCE_LOCAL_STORAGE")


def _env_flag(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _current_root_prefix() -> str:
    """Return the active storage root prefix from the live environment."""

    env_value = os.getenv("S3_ROOT_PREFIX")
    if env_value is None:
        return ""
    return env_value.strip().strip("/")

req = {
    "AWS_ACCESS_KEY_ID": AWS_ACCESS_KEY_ID,
    "AWS_SECRET_ACCESS_KEY": AWS_SECRET_ACCESS_KEY,
    "S3_BUCKET": S3_BUCKET,
}
missing = [k for k, v in req.items() if not v]
_force_local = _env_flag(FORCE_LOCAL_STORAGE)
_USE_SPACES = not missing and not _force_local

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
    try:
        # Detect environments where outbound network access is blocked.
        _s3.list_objects_v2(Bucket=S3_BUCKET, MaxKeys=1)
    except EndpointConnectionError:
        _s3 = None
        _USE_SPACES = False
else:
    _s3 = None

# ===== Helpers =====
def _normalize_key(user_path: str) -> str:
    """Normaliseer ``user_path`` naar een object key.

    Een lege ``user_path`` verwijst naar de root van de bucket of, wanneer
    ``S3_ROOT_PREFIX`` is ingesteld, naar die prefix.  Hierdoor kunnen
    aanroepers eenvoudig het root-pad opvragen zonder een fout te krijgen,
    iets wat voorheen de hele archiefweergave kon breken wanneer de prefix
    leeg was geconfigureerd.
    """

    if user_path is None:
        raise ValueError("Pad mag niet None zijn.")

    p = user_path.replace("\\", "/").strip()
    if not p:
        root = _current_root_prefix().replace("\\", "/").strip().strip("/")
        return root

    p = p.lstrip("/")
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        raise ValueError("Path traversal niet toegestaan.")
    rel = "/".join(parts)
    root_prefix = _current_root_prefix()
    if root_prefix:
        root = root_prefix.replace("\\", "/").strip().strip("/")
        # Prevent double-prefix (if caller already included the root prefix)
        if rel == root or rel.startswith(root + "/"):
            return rel
        return f"{root}/{rel}" if rel else root
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

    def save_text(path: str, content: str | IO, content_type: str = "text/plain; charset=utf-8") -> None:
        key = _normalize_key(path)
        parent = str(PurePosixPath(key).parent)
        if parent and parent != ".":
            ensure_dir(parent)
        if isinstance(content, str):
            body = content.encode("utf-8")
            _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType=content_type)
        else:
            content.seek(0)
            if getattr(content, "encoding", None):
                import io as _io
                content = _io.BytesIO(content.read().encode("utf-8"))
                content.seek(0)
            _s3.upload_fileobj(content, S3_BUCKET, key, ExtraArgs={"ContentType": content_type})

    def save_json(path: str, obj) -> None:
        key = _normalize_key(path)
        parent = str(PurePosixPath(key).parent)
        if parent and parent != ".":
            ensure_dir(parent)
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        _s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, ContentType="application/json; charset=utf-8")

    def read_text(path: str, max_bytes: int | None = None) -> str:
        key = _normalize_key(path)
        try:
            params = {"Bucket": S3_BUCKET, "Key": key}
            if max_bytes is not None:
                params["Range"] = f"bytes=0-{max_bytes - 1}"
            res = _s3.get_object(**params)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(path)
            raise
        body = res["Body"].read(max_bytes) if max_bytes is not None else res["Body"].read()
        return body.decode("utf-8", errors="replace")

    def read_json(path: str, *, with_etag: bool = False):
        """Read JSON object and optionally return its ETag."""
        key = _normalize_key(path)
        try:
            obj = _s3.get_object(Bucket=S3_BUCKET, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                if with_etag:
                    return None, None
                raise FileNotFoundError(path)
            raise
        body = obj["Body"].read()
        data = json.loads(body.decode("utf-8"))
        etag = obj.get("ETag", "").strip('"')
        if with_etag:
            return data, etag
        return data

    def write_json(path: str, data: dict, *, etag: str | None = None) -> bool:
        """Write JSON data, optionally enforcing an ETag match."""
        key = _normalize_key(path)
        body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        extra = {}
        if etag:
            extra["IfMatch"] = etag
        try:
            _s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=body,
                ACL="private",
                ContentType="application/json",
                **extra,
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "PreconditionFailed":
                return False
            raise
        return True

    def backup_json(path: str, data: dict) -> None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_key = f"backups/{path.rstrip('.json')}-{ts}.json"
        write_json(backup_key, data)

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

    def read_file(path: str) -> Tuple[bytes, str]:
        """Download a binary file and return its bytes and content type."""

        key = _normalize_key(path)
        try:
            obj = _s3.get_object(Bucket=S3_BUCKET, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(path)
            raise
        data = obj["Body"].read()
        content_type = obj.get("ContentType") or "application/octet-stream"
        return data, content_type
else:
    # ===== Local filesystem fallback =====
    _LOCAL_ROOT_OVERRIDE = None

    def set_local_root(path: str | None) -> None:
        """Override the local storage root used for filesystem fallbacks."""

        global _LOCAL_ROOT_OVERRIDE
        if path:
            _LOCAL_ROOT_OVERRIDE = str(path)
        else:
            _LOCAL_ROOT_OVERRIDE = None

    def _local_root() -> str:
        if _LOCAL_ROOT_OVERRIDE:
            return _LOCAL_ROOT_OVERRIDE
        env_override = os.getenv("SPECTRE_LOCAL_ROOT") or os.getenv("SPACES_ROOT")
        if env_override:
            return env_override
        module = sys.modules.get("utils")
        candidate = getattr(module, "DOSSIERS_DIR", None) if module else None
        if candidate:
            try:
                candidate_path = os.fspath(candidate)
            except TypeError:
                candidate_path = None
            if candidate_path:
                return candidate_path
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

        prefix = _current_root_prefix()
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

    def save_text(path: str, content: str | IO, content_type: str = "text/plain; charset=utf-8") -> None:
        fp = _local_path(_normalize_key(path))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        if isinstance(content, str):
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            content.seek(0)
            if getattr(content, "encoding", None):
                with open(fp, "w", encoding="utf-8") as f:
                    shutil.copyfileobj(content, f)
            else:
                with open(fp, "wb") as f:
                    shutil.copyfileobj(content, f)

    def save_json(path: str, obj) -> None:
        save_text(path, json.dumps(obj, ensure_ascii=False, indent=2), "application/json; charset=utf-8")

    def read_text(path: str, max_bytes: int | None = None) -> str:
        fp = _local_path(_normalize_key(path))
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return f.read(max_bytes) if max_bytes is not None else f.read()
        except FileNotFoundError:
            raise FileNotFoundError(path)

    def read_json(path: str, *, with_etag: bool = False):
        fp = _local_path(_normalize_key(path))
        try:
            with open(fp, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            if with_etag:
                return None, None
            raise FileNotFoundError(path)
        etag = hashlib.md5(body).hexdigest()
        data = json.loads(body.decode("utf-8"))
        if with_etag:
            return data, etag
        return data

    def write_json(path: str, data: dict, *, etag: str | None = None) -> bool:
        fp = _local_path(_normalize_key(path))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        if etag and os.path.exists(fp):
            with open(fp, "rb") as f:
                current = f.read()
            if hashlib.md5(current).hexdigest() != etag:
                return False
        with open(fp, "wb") as f:
            f.write(body)
        return True

    def backup_json(path: str, data: dict) -> None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_key = f"backups/{path.rstrip('.json')}-{ts}.json"
        write_json(backup_key, data)

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

    def read_file(path: str) -> Tuple[bytes, str]:
        fp = _local_path(_normalize_key(path))
        try:
            with open(fp, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            raise FileNotFoundError(path)
        content_type = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        return data, content_type
