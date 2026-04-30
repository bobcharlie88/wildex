from __future__ import annotations

import mimetypes
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.utils.media_urls import is_remote_media_url, local_upload_path_from_url

router = APIRouter()


def _safe_local_upload(url: str) -> Path:
    path = local_upload_path_from_url(url)
    try:
        resolved = path.resolve()
        root = Path("uploads").resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Upload path escaped uploads directory")
    except Exception as exc:
        raise HTTPException(400, "Invalid local upload path") from exc
    return path


def _remote_url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for item in addresses:
        host = item[4][0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


@router.get("/media/image")
def get_media_image(url: str = Query(..., min_length=1)):
    if url.startswith("/uploads/"):
        local_path = _safe_local_upload(url)
        if not local_path.exists():
            raise HTTPException(404, "Local media file is missing")
        media_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        return FileResponse(local_path, media_type=media_type)

    if not is_remote_media_url(url):
        raise HTTPException(400, "Only upload or HTTP(S) media URLs can be proxied")
    if not _remote_url_allowed(url):
        raise HTTPException(400, "Remote media host is not allowed")

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Remote media could not be loaded") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Remote media could not be loaded") from exc

    content_type = response.headers.get("content-type") or mimetypes.guess_type(url)[0] or "application/octet-stream"
    if not content_type.lower().startswith("image/"):
        raise HTTPException(415, "Remote media is not an image")
    return Response(
        content=response.content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
