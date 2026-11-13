"""Streamer video ingestion — uploads only; no platform scrapers."""
from __future__ import annotations

from typing import Any, Dict, Optional


URL_NOT_SUPPORTED = (
    "URL ingestion is not available. Upload an MP4/MOV you have permission to use, "
    "or use an official/permitted download method. This app does not scrape or bypass "
    "platform restrictions, login walls, or DRM."
)


def validate_clip_request(payload: Dict[str, Any]) -> None:
    url = (payload.get("source_url") or payload.get("url") or "").strip()
    video_url = (payload.get("video_url") or "").strip()
    if url and not video_url:
        raise ValueError(URL_NOT_SUPPORTED)
    if not video_url and not payload.get("video_id"):
        raise ValueError("Upload a video file first (MP4/MOV).")


def create_clip_job_payload(
    *,
    video_id: str,
    streamer_name: str = "",
    clip_count: int = 8,
    target_duration_sec: int = 30,
    template: str = "facecam_top",
) -> Dict[str, Any]:
    return {
        "video_id": video_id,
        "streamer_name": streamer_name,
        "clip_count": max(1, min(30, int(clip_count or 8))),
        "target_duration_sec": max(10, min(90, int(target_duration_sec or 30))),
        "template": template or "facecam_top",
    }
