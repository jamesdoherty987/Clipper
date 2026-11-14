"""Streamer video ingestion — file upload or YouTube / direct media URL."""
from __future__ import annotations

from typing import Any, Dict

from app.studio.streamer_clips.clip_style import normalize_clip_style
from app.studio.url_ingest import download_source_url, is_supported_source_url


def validate_clip_request(payload: Dict[str, Any]) -> None:
    url = (payload.get("source_url") or payload.get("url") or "").strip()
    video_url = (payload.get("video_url") or "").strip()
    video_id = (payload.get("video_id") or "").strip()
    if video_id or video_url:
        return
    if url:
        if not is_supported_source_url(url):
            raise ValueError(
                "Unsupported URL. Use a YouTube link or a direct .mp4/.mov/.webm URL."
            )
        return
    raise ValueError("Upload a video file or paste a YouTube / direct media URL.")


def ingest_source_url_as_video(store, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Download source_url and create a gta_video row."""
    url = (payload.get("source_url") or payload.get("url") or "").strip()
    downloaded = download_source_url(url)
    return store.create_gta_video({
        "name": (payload.get("name") or downloaded.get("name") or "Imported video").strip(),
        "kind": "streamer",
        "url": downloaded["url"],
        "content_type": downloaded.get("content_type") or "video/mp4",
        "size_bytes": downloaded.get("size_bytes") or 0,
        "duration_sec": downloaded.get("duration_sec"),
        "source_id": payload.get("source_id") or "",
        "streamer_name": payload.get("streamer_name") or "",
        "created_by": payload.get("created_by") or "local",
        "tags": ["imported", "youtube"] if downloaded.get("platform_id") else ["imported"],
    })


def create_clip_job_payload(
    *,
    video_id: str,
    streamer_name: str = "",
    clip_count: int = 8,
    target_duration_sec: int = 30,  # respected as-is (8–120); no forced 60s floor
    template: str = "fullscreen_gameplay",
    video_context: str = "",
    **style_overrides: Any,
) -> Dict[str, Any]:
    style = normalize_clip_style({
        "template": template,
        **style_overrides,
    })
    return {
        "video_id": video_id,
        "streamer_name": streamer_name,
        "video_context": (video_context or "").strip()[:1200],
        "clip_count": max(1, min(30, int(clip_count or 8))),
        "target_duration_sec": max(8, min(120, int(target_duration_sec or 30))),
        "template": style["template"],
        "style": style,
        # Flat mirrors for older readers / UI summaries
        "burn_captions": style["burn_captions"],
        "add_intro": style["add_intro"],
        "add_end_card": style["add_end_card"],
        "show_logo": style["show_logo"],
        "apply_zoom": style["apply_zoom"],
        "preset": style["preset"],
    }
