"""Download remote video URLs (YouTube etc.) into local media storage."""
from __future__ import annotations

import logging
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from app.r2_compat import MEDIA

logger = logging.getLogger(__name__)

_YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "music.youtube.com",
}


def is_supported_source_url(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host in _YT_HOSTS or host.endswith(".youtube.com"):
        return True
    # Direct media links
    path = (parsed.path or "").lower()
    return any(path.endswith(ext) for ext in (".mp4", ".mov", ".webm", ".m4v", ".mkv"))


def _import_local_file(src: Path, *, folder: str = "videos", prefix: str = "ytdl") -> Tuple[str, int, str]:
    if not src.exists() or src.stat().st_size <= 0:
        raise RuntimeError("Download produced an empty file")
    dest_dir = MEDIA / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = (src.suffix.lstrip(".") or "mp4").lower()[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{secrets.token_hex(4)}.{ext}"
    dest = dest_dir / filename
    shutil.copy2(src, dest)
    size = dest.stat().st_size
    import os

    base = (os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8787").rstrip("/")
    url = f"{base}/media/{dest.relative_to(MEDIA).as_posix()}"
    content_type = {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "m4v": "video/x-m4v",
        "mkv": "video/x-matroska",
    }.get(ext, "video/mp4")
    return url, size, content_type


def download_source_url(url: str) -> Dict[str, Any]:
    """
    Download a YouTube (or direct media) URL to local /media and return metadata.
    Caller must have rights to use the content.
    """
    url = (url or "").strip()
    if not is_supported_source_url(url):
        raise ValueError(
            "Unsupported URL. Use a YouTube link or a direct .mp4/.mov/.webm URL."
        )

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    is_youtube = host in _YT_HOSTS or host.endswith(".youtube.com")

    if not is_youtube:
        # Direct file — stream via requests into media
        import requests

        with tempfile.TemporaryDirectory(prefix="gta_url_") as tmp:
            suffix = Path(parsed.path).suffix or ".mp4"
            tmp_path = Path(tmp) / f"direct{suffix}"
            with requests.get(url, stream=True, timeout=600) as res:
                res.raise_for_status()
                with tmp_path.open("wb") as f:
                    for chunk in res.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            media_url, size, content_type = _import_local_file(tmp_path, prefix="url")
            name = Path(parsed.path).name or "Downloaded video"
            return {
                "url": media_url,
                "name": name,
                "content_type": content_type,
                "size_bytes": size,
                "source_url": url,
                "duration_sec": None,
            }

    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from e

    with tempfile.TemporaryDirectory(prefix="gta_ytdl_") as tmp:
        outtmpl = str(Path(tmp) / "%(id)s.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:
            msg = str(e).strip() or e.__class__.__name__
            raise RuntimeError(f"Could not download URL: {msg}") from e

        if info is None:
            raise RuntimeError("Download returned no metadata")
        # playlist guard
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0] or info

        video_id = info.get("id") or "video"
        requested = info.get("requested_downloads") or []
        filepath = None
        if requested and requested[0].get("filepath"):
            filepath = Path(requested[0]["filepath"])
        if filepath is None or not filepath.exists():
            # Fall back to scanning temp dir
            candidates = sorted(Path(tmp).glob(f"{video_id}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
            candidates = [p for p in candidates if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4a"}]
            if not candidates:
                candidates = list(Path(tmp).iterdir())
            if not candidates:
                raise RuntimeError("Download finished but no media file was found")
            filepath = candidates[0]

        media_url, size, content_type = _import_local_file(filepath, prefix="yt")
        title = (info.get("title") or f"YouTube {video_id}").strip()
        # sanitize overly long titles
        title = re.sub(r"\s+", " ", title)[:120]
        duration = info.get("duration")
        try:
            duration_sec = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_sec = None

        return {
            "url": media_url,
            "name": title,
            "content_type": content_type,
            "size_bytes": size,
            "source_url": url,
            "duration_sec": duration_sec,
            "platform_id": video_id,
        }
