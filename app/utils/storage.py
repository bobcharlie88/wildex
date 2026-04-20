import io
import logging
import mimetypes
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import (
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET_NAME,
    R2_PUBLIC_BASE_URL,
    R2_SECRET_ACCESS_KEY,
)

log = logging.getLogger("wildex.storage")
LOCAL_UPLOADS_DIR = Path("uploads")


def r2_enabled() -> bool:
    return all([
        R2_ACCOUNT_ID,
        R2_ACCESS_KEY_ID,
        R2_SECRET_ACCESS_KEY,
        R2_BUCKET_NAME,
        R2_PUBLIC_BASE_URL,
    ])


def _r2_client():
    if not r2_enabled():
        raise RuntimeError("Cloudflare R2 is not fully configured")
    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _public_url(key: str) -> str:
    return f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"


def _local_url(filename: str) -> str:
    return f"/uploads/{filename}"


def _write_local_bytes(data: bytes, suffix: str | None = None) -> str:
    ext = (suffix or ".bin").lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    LOCAL_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    path = LOCAL_UPLOADS_DIR / filename
    path.write_bytes(data)
    return _local_url(filename)


def _write_local_file(image_path: str) -> str:
    path = Path(image_path)
    return _write_local_bytes(path.read_bytes(), suffix=path.suffix or ".bin")


def upload_bytes(data: bytes, content_type: str | None, suffix: str | None = None) -> str:
    ext = suffix or mimetypes.guess_extension(content_type or "") or ".bin"
    key = f"captures/{uuid4().hex}{ext.lower()}"
    fileobj = io.BytesIO(data)
    extra = {"ContentType": content_type or "application/octet-stream"}
    _r2_client().upload_fileobj(fileobj, R2_BUCKET_NAME, key, ExtraArgs=extra)
    return _public_url(key)


def upload_file(image_path: str, content_type: str | None = None) -> str:
    path = Path(image_path)
    guessed_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    key = f"captures/{uuid4().hex}{path.suffix.lower() or '.bin'}"
    extra = {"ContentType": guessed_type}
    with path.open("rb") as fh:
        _r2_client().upload_fileobj(fh, R2_BUCKET_NAME, key, ExtraArgs=extra)
    return _public_url(key)


def upload_capture_asset(
    *,
    original_bytes: bytes,
    original_content_type: str | None,
    original_suffix: str,
    extracted_frame_path: str | None = None,
) -> str | None:
    try:
        if extracted_frame_path:
            return upload_file(extracted_frame_path, content_type="image/jpeg")
        return upload_bytes(
            original_bytes,
            content_type=original_content_type,
            suffix=original_suffix,
        )
    except (BotoCoreError, ClientError, RuntimeError, OSError) as exc:
        log.exception("R2 upload failed: %s", exc)
        try:
            if extracted_frame_path:
                local_url = _write_local_file(extracted_frame_path)
            else:
                local_url = _write_local_bytes(original_bytes, suffix=original_suffix)
            log.warning("Fell back to local upload storage: %s", local_url)
            return local_url
        except OSError as local_exc:
            log.exception("Local upload fallback failed: %s", local_exc)
            return None
