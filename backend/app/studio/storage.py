"""Upload / download helpers for GTA Content Studio (R2 folder ops/gta)."""
from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests

from app.r2_compat import upload_bytes, upload_path

logger = logging.getLogger(__name__)

GTA_FOLDER = "ops/gta"


def upload_gta_bytes(
    raw: bytes,
    *,
    filename: str,
    content_type: str,
    folder: str = GTA_FOLDER,
) -> str:
    return upload_bytes(raw, filename=filename, content_type=content_type, folder=folder)


def upload_gta_path(
    path: Path,
    *,
    content_type: str = "video/mp4",
    folder: str = GTA_FOLDER,
    prefix: str = "gta",
) -> Tuple[str, str]:
    return upload_path(path, content_type=content_type, folder=folder, prefix=prefix)


def download_to_temp(url: str, *, suffix: str = ".mp4") -> Path:
    """Download an HTTP(S), local /media, or data: URL to a temp file."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Empty media URL")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        if url.startswith("data:"):
            header, _, b64 = url.partition(",")
            if ";base64" not in header or not b64:
                raise ValueError("Unsupported data URL")
            tmp_path.write_bytes(base64.b64decode(b64))
            return tmp_path
        # Local media served by this app
        if "/media/" in url:
            from app.r2_compat import MEDIA
            rel = url.split("/media/", 1)[1].split("?", 1)[0]
            local = MEDIA / rel
            if local.exists():
                tmp_path.write_bytes(local.read_bytes())
                return tmp_path
        if url.startswith("file://"):
            src = Path(url.replace("file://", ""))
            tmp_path.write_bytes(src.read_bytes())
            return tmp_path
        res = requests.get(url, timeout=300)
        res.raise_for_status()
        tmp_path.write_bytes(res.content)
        return tmp_path
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def suffix_from_url_or_type(url: str = "", content_type: str = "") -> str:
    ct = (content_type or "").lower()
    if "quicktime" in ct or ct.endswith("/mov"):
        return ".mov"
    if "webm" in ct:
        return ".webm"
    if "wav" in ct:
        return ".wav"
    if "mpeg" in ct or "mp3" in ct:
        return ".mp3"
    path = urlparse(url or "").path
    for ext in (".mp4", ".mov", ".webm", ".m4v", ".mkv", ".wav", ".mp3"):
        if path.lower().endswith(ext):
            return ext
    return ".mp4"
