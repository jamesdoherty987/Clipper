"""Gameplay library ingest with frame sampling + AI tagging + embeddings."""
from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.studio.analysis.frames import extract_frame, extract_frames
from app.studio.analysis.scene_detection import detect_scene_changes, sample_interval_times
from app.studio.analysis.vision import describe_gameplay_frame
from app.studio.costing import estimate_library_ingest_cost
from app.studio.gameplay_library.embeddings import embed_text, segment_embed_text
from app.studio.storage import download_to_temp, suffix_from_url_or_type, upload_gta_path
from app.studio.video_engine.ffmpeg import ffmpeg_available, media_info

logger = logging.getLogger(__name__)


def create_segment_from_video(
    store,
    *,
    video_id: str,
    name: str = "",
    description: str = "",
    tags: Any = None,
    start_sec: float = 0,
    end_sec: float = 0,
    source_id: str = "",
    created_by: str = "",
    embedding: Optional[List[float]] = None,
    thumbnail_url: str = "",
    action_level: Any = None,
    setting: str = "",
    quality_score: Any = None,
) -> Dict[str, Any]:
    video = store.get_gta_video(video_id)
    if not video:
        raise ValueError("Video not found")
    tag_list = tags or video.get("tags") or []
    if isinstance(tag_list, str):
        tag_list = [t.strip() for t in tag_list.split(",") if t.strip()]
    duration = video.get("duration_sec")
    if not end_sec or end_sec <= start_sec:
        end_sec = float(duration or end_sec or 30)
    return store.create_gta_segment({
        "video_id": video_id,
        "name": name or video.get("name") or "Gameplay segment",
        "url": video.get("url") or "",
        "start_sec": float(start_sec or 0),
        "end_sec": float(end_sec),
        "description": description or "",
        "tags": tag_list,
        "embedding": embedding,
        "thumbnail_url": thumbnail_url,
        "action_level": action_level,
        "setting": setting,
        "quality_score": quality_score,
        "source_id": source_id or video.get("source_id") or "",
        "created_by": created_by,
    })


def _progress(store, job_id: str, **fields):
    store.update_gta_job(job_id, {"status": "processing", **fields})


def start_library_ingest_job(store, job_id: str) -> None:
    """Index a gameplay video into multiple AI-tagged segments."""
    job = store.get_gta_job(job_id)
    if not job:
        return
    payload = dict(job.get("payload") or {})
    video_id = (payload.get("video_id") or "").strip()
    work = Path(tempfile.mkdtemp(prefix="gta_lib_"))
    temps: List[Path] = []
    try:
        if not ffmpeg_available():
            raise RuntimeError("ffmpeg/ffprobe required for library indexing")
        video = store.get_gta_video(video_id)
        if not video or not video.get("url"):
            raise ValueError("Video not found")

        _progress(store, job_id, stage="download", progress="Downloading gameplay…", progress_percent=8)
        src = download_to_temp(
            video["url"],
            suffix=suffix_from_url_or_type(video.get("url") or "", video.get("content_type") or ""),
        )
        temps.append(src)
        info = media_info(src)
        duration = float(info.get("duration_sec") or payload.get("end_sec") or 60)

        # Optional manual single-segment override
        if payload.get("manual_only"):
            segment = create_segment_from_video(
                store,
                video_id=video_id,
                name=payload.get("name") or "",
                description=payload.get("description") or "",
                tags=payload.get("tags"),
                start_sec=float(payload.get("start_sec") or 0),
                end_sec=float(payload.get("end_sec") or duration),
                source_id=payload.get("source_id") or "",
                created_by=job.get("created_by") or "",
            )
            store.update_gta_job(job_id, {
                "status": "complete",
                "stage": "complete",
                "progress": "Indexed (manual)",
                "progress_percent": 100,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result": {"segment_ids": [segment.get("id")], "mode": "manual"},
            })
            return

        _progress(store, job_id, stage="scenes", progress="Detecting scenes…", progress_percent=18)
        scenes = detect_scene_changes(src, threshold=0.32)
        scene_times = [s["time_sec"] for s in scenes]
        interval_times = sample_interval_times(duration, every_sec=max(8.0, min(20.0, duration / 10)))
        # Build sample points: prefer scene cuts, fill with intervals, cap count
        points = sorted(set([0.0] + scene_times + interval_times))
        # Drop points too close together
        filtered = []
        for t in points:
            if t >= duration - 0.5:
                continue
            if filtered and (t - filtered[-1]) < 6.0:
                continue
            filtered.append(t)
        # Limit vision cost on long VODs
        max_frames = int(payload.get("max_frames") or 18)
        if len(filtered) > max_frames:
            step = len(filtered) / max_frames
            filtered = [filtered[int(i * step)] for i in range(max_frames)]

        cost = estimate_library_ingest_cost(duration_sec=duration, frame_count=len(filtered) or 1)
        store.update_gta_job(job_id, {"cost_estimate": cost})

        _progress(
            store, job_id,
            stage="frames",
            progress=f"Extracting {len(filtered)} frames…",
            progress_percent=28,
        )
        frame_dir = work / "frames"
        frames = extract_frames(src, filtered, frame_dir, prefix="gp")

        user_tags = payload.get("tags") or []
        if isinstance(user_tags, str):
            user_tags = [t.strip() for t in user_tags.split(",") if t.strip()]

        segment_ids: List[str] = []
        for i, (t, frame_path) in enumerate(zip(filtered, frames)):
            pct = 30 + int(55 * ((i + 1) / max(1, len(frames))))
            _progress(
                store, job_id,
                stage="vision",
                progress=f"AI tagging segment {i + 1}/{len(frames)}…",
                progress_percent=pct,
            )
            next_t = filtered[i + 1] if i + 1 < len(filtered) else min(duration, t + 12)
            end_t = max(t + 3.0, float(next_t) - 0.15)

            desc = {
                "description": payload.get("description") or "",
                "tags": list(user_tags),
                "action_level": None,
                "setting": "",
            }
            try:
                desc = describe_gameplay_frame(
                    frame_path,
                    context=payload.get("name") or video.get("name") or "",
                )
            except Exception as e:
                logger.warning("[GTA] vision tag failed at %s: %s", t, e)

            tags = list(dict.fromkeys([*(desc.get("tags") or []), *user_tags]))
            thumb_url = ""
            try:
                thumb_url, _ = upload_gta_path(frame_path, content_type="image/jpeg", prefix="gta_thumb")
            except Exception:
                pass

            text_for_embed = " ".join([
                payload.get("name") or video.get("name") or "",
                desc.get("description") or "",
                " ".join(tags),
            ]).strip()
            embedding = None
            try:
                if text_for_embed:
                    embedding = embed_text(text_for_embed)
            except Exception as e:
                logger.warning("[GTA] embed failed: %s", e)

            quality = None
            if desc.get("action_level"):
                quality = float(desc["action_level"]) / 5.0
            seg = create_segment_from_video(
                store,
                video_id=video_id,
                name=(payload.get("name") or video.get("name") or "Gameplay") + f" · {int(t)}s",
                description=desc.get("description") or payload.get("description") or "",
                tags=tags,
                start_sec=t,
                end_sec=end_t,
                source_id=payload.get("source_id") or video.get("source_id") or "",
                created_by=job.get("created_by") or "",
                embedding=embedding,
                thumbnail_url=thumb_url,
                action_level=desc.get("action_level"),
                setting=desc.get("setting") or "",
                quality_score=quality,
            )
            segment_ids.append(seg["id"])

        # If vision produced nothing, fall back to one manual segment
        if not segment_ids:
            seg = create_segment_from_video(
                store,
                video_id=video_id,
                name=payload.get("name") or video.get("name") or "Gameplay",
                description=payload.get("description") or "",
                tags=user_tags,
                start_sec=0,
                end_sec=duration,
                source_id=payload.get("source_id") or "",
                created_by=job.get("created_by") or "",
            )
            segment_ids = [seg["id"]]

        store.update_gta_job(job_id, {
            "status": "complete",
            "stage": "complete",
            "progress": f"Indexed {len(segment_ids)} segments",
            "progress_percent": 100,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "cost_estimate": cost,
            "result": {
                "segment_ids": segment_ids,
                "frame_count": len(frames),
                "duration_sec": duration,
            },
        })
    except Exception as e:
        logger.exception("[GTA] library ingest failed")
        store.update_gta_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress": "Failed",
            "error": str(e)[:800],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        raise
    finally:
        for p in temps:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        shutil.rmtree(work, ignore_errors=True)
