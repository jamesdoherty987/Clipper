"""Local media storage (optional R2 later). Files are served from /media."""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Tuple
ROOT = Path(os.getenv("GTACLIPPER_DATA") or Path(__file__).resolve().parents[2] / "data")
MEDIA = ROOT / "media"
MEDIA.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def media_path_from_url(url: str) -> Path | None:
    """Resolve a /media/... URL to a local file path inside MEDIA."""
    url = (url or "").strip()
    if not url or "/media/" not in url:
        return None
    rel = url.split("/media/", 1)[1].split("?", 1)[0]
    # Guard against path traversal
    candidate = (MEDIA / rel).resolve()
    try:
        candidate.relative_to(MEDIA.resolve())
    except ValueError:
        return None
    return candidate


def delete_media_url(url: str) -> bool:
    path = media_path_from_url(url)
    if not path or not path.exists() or not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except Exception as e:
        logger.warning("Failed to delete media %s: %s", path, e)
        return False


def upload_bytes(
    raw: bytes,
    *,
    filename: str,
    content_type: str,
    folder: str = "uploads",
) -> str:
    dest_dir = MEDIA / folder.replace("ops/gta/", "").replace("ops/gta", "uploads")
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = filename.replace("/", "_")
    path = dest_dir / safe
    path.write_bytes(raw)
    rel = path.relative_to(MEDIA).as_posix()
    base = (os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8787").rstrip("/")
    return f"{base}/media/{rel}"


def upload_path(
    path: Path,
    *,
    content_type: str,
    folder: str = "uploads",
    prefix: str = "gta",
) -> Tuple[str, str]:
    ext = path.suffix.lstrip(".") or "bin"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{secrets.token_hex(4)}.{ext}"
    url = upload_bytes(path.read_bytes(), filename=filename, content_type=content_type, folder=folder)
    return url, filename
