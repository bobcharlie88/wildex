import io
import logging
import mimetypes
import re
from pathlib import Path
from uuid import uuid4

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # Local/dev environments may use local upload fallback only.
    boto3 = None

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        pass

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
    if boto3 is None:
        raise RuntimeError("boto3 is not installed")
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


def slugify_filename(value: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return base or uuid4().hex[:12]


def _write_local_bytes(data: bytes, suffix: str | None = None) -> str:
    ext = (suffix or ".bin").lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    LOCAL_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    path = LOCAL_UPLOADS_DIR / filename
    path.write_bytes(data)
    return _local_url(filename)


def _write_local_bytes_in_dir(data: bytes, directory: str, filename: str) -> str:
    safe_dir = Path(*[slugify_filename(part) for part in str(directory or "").split("/") if part])
    safe_name = Path(filename).name
    root = LOCAL_UPLOADS_DIR / safe_dir
    root.mkdir(parents=True, exist_ok=True)
    path = root / safe_name
    path.write_bytes(data)
    public_parts = "/".join(["uploads", *(part for part in safe_dir.parts), safe_name])
    return f"/{public_parts}"


def _write_local_file(image_path: str) -> str:
    path = Path(image_path)
    return _write_local_bytes(path.read_bytes(), suffix=path.suffix or ".bin")


def upload_bytes(data: bytes, content_type: str | None, suffix: str | None = None) -> str:
    ext = suffix or mimetypes.guess_extension(content_type or "") or ".bin"
    key = f"captures/{uuid4().hex}{ext.lower()}"
    fileobj = io.BytesIO(data)
    extra = {"ContentType": content_type or "application/octet-stream"}
    _r2_client().upload_fileobj(fileobj, R2_BUCKET_NAME, key, ExtraArgs=extra)
    url = _public_url(key)
    log.info("Uploaded capture asset to R2: %s", url)
    return url


def upload_named_bytes(
    *,
    data: bytes,
    content_type: str | None,
    directory: str,
    filename: str,
) -> str:
    suffix = Path(filename).suffix or mimetypes.guess_extension(content_type or "") or ".bin"
    safe_filename = f"{slugify_filename(Path(filename).stem)}-{uuid4().hex[:8]}{suffix.lower()}"
    key = "/".join(
        ["admin-assets", *(slugify_filename(part) for part in str(directory or "").split("/") if part), safe_filename]
    )
    if r2_enabled():
        fileobj = io.BytesIO(data)
        extra = {"ContentType": content_type or "application/octet-stream"}
        _r2_client().upload_fileobj(fileobj, R2_BUCKET_NAME, key, ExtraArgs=extra)
        url = _public_url(key)
        log.info("Uploaded admin asset to R2: %s", url)
        return url
    url = _write_local_bytes_in_dir(data, f"admin/{directory}", safe_filename)
    log.info("Stored admin asset locally: %s", url)
    return url


def upload_file(image_path: str, content_type: str | None = None) -> str:
    path = Path(image_path)
    guessed_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    key = f"captures/{uuid4().hex}{path.suffix.lower() or '.bin'}"
    extra = {"ContentType": guessed_type}
    with path.open("rb") as fh:
        _r2_client().upload_fileobj(fh, R2_BUCKET_NAME, key, ExtraArgs=extra)
    url = _public_url(key)
    log.info("Uploaded derived capture asset to R2: %s", url)
    return url


def persist_capture_media(
    *,
    original_bytes: bytes,
    original_content_type: str | None,
    original_suffix: str,
    extracted_frame_path: str | None = None,
) -> dict[str, str | None]:
    original_url = None
    primary_url = None
    errors: list[str] = []

    try:
        original_url = upload_bytes(
            original_bytes,
            content_type=original_content_type,
            suffix=original_suffix,
        )
    except (BotoCoreError, ClientError, RuntimeError, OSError) as exc:
        log.exception("Original upload failed: %s", exc)
        try:
            original_url = _write_local_bytes(original_bytes, suffix=original_suffix)
            log.warning("Fell back to local upload storage for original asset: %s", original_url)
        except OSError as local_exc:
            log.exception("Local fallback failed for original upload: %s", local_exc)
            errors.append(str(local_exc))

    if extracted_frame_path:
        try:
            primary_url = upload_file(extracted_frame_path, content_type="image/jpeg")
        except (BotoCoreError, ClientError, RuntimeError, OSError) as exc:
            log.exception("Primary frame upload failed: %s", exc)
            try:
                primary_url = _write_local_file(extracted_frame_path)
                log.warning("Fell back to local upload storage for primary frame: %s", primary_url)
            except OSError as local_exc:
                log.exception("Local fallback failed for primary frame upload: %s", local_exc)
                errors.append(str(local_exc))
    else:
        primary_url = original_url

    return {
        "original_url": original_url,
        "primary_url": primary_url,
        "error": "; ".join(error for error in errors if error) or None,
    }


def upload_capture_asset(
    *,
    original_bytes: bytes,
    original_content_type: str | None,
    original_suffix: str,
    extracted_frame_path: str | None = None,
) -> str | None:
    result = persist_capture_media(
        original_bytes=original_bytes,
        original_content_type=original_content_type,
        original_suffix=original_suffix,
        extracted_frame_path=extracted_frame_path,
    )
    return result["primary_url"]
