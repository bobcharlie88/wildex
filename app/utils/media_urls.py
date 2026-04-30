from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

LOCAL_UPLOADS_DIR = Path("uploads")


def is_remote_media_url(url: str | None) -> bool:
    lowered = (url or "").strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def media_url_for_client(url: str | None) -> str | None:
    if not url:
        return url
    if is_remote_media_url(url):
        return f"/media/image?url={quote(url, safe='')}"
    return url


def local_upload_path_from_url(url: str) -> Path:
    if not url.startswith("/uploads/"):
        raise ValueError("URL is not a local upload path")
    relative = url.removeprefix("/uploads/").replace("\\", "/")
    parts = [part for part in relative.split("/") if part not in {"", ".", ".."}]
    return LOCAL_UPLOADS_DIR.joinpath(*parts)
