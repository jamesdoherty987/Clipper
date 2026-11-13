"""Local media storage (optional R2 later). Files are served from /media."""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Tuple

ROOT = Path(os.getenv("GTACLIPPER_DATA") or Path(__file__).resolve().parents[2] / "data")
MEDIA = ROOT / "media"
MEDIA.mkdir(parents=True, exist_ok=True)


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
