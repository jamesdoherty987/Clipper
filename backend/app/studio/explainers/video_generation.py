"""Explainer render job: transcribe → align → select gameplay → FFmpeg assemble."""
from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.studio.costing import estimate_explainer_cost
from app.studio.explainers.gameplay_selection import select_gameplay_for_sections
from app.studio.explainers.recording_analysis import analyze_recording
from app.studio.storage import download_to_temp, suffix_from_url_or_type, upload_gta_path
from app.studio.video_engine.captions import segments_to_ass
from app.studio.video_engine.ffmpeg import (
    burn_subtitles,
    concat_clips,
    ffmpeg_available,
    media_info,
    mix_music,
    trim_clip,
)
from app.studio.video_engine.overlays import apply_branding
from app.studio.video_engine.templates import compose_layout

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _progress(store, job_id: str, *, stage: str, progress: str, percent: int, **extra):
    payload = {
        "status": "processing",
        "stage": stage,
        "progress": progress,
        "progress_percent": max(0, min(100, int(percent))),
        **extra,
    }
    store.update_gta_job(job_id, payload)


def start_explainer_job(store, job_id: str) -> None:
    job = store.get_gta_job(job_id)
    if not job:
        return
    if not ffmpeg_available():
        store.update_gta_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress": "FFmpeg not available",
            "error": "ffmpeg/ffprobe must be installed on PATH",
        })
        return

    payload = dict(job.get("payload") or {})
    script_id = (payload.get("script_id") or "").strip()
    recording_id = (payload.get("recording_id") or "").strip()
    template = (payload.get("template") or "").strip()
    settings = store.get_gta_settings()
    if not template:
        template = settings.get("default_template") or "facecam_top"

    script = store.get_gta_script(script_id) if script_id else None
    recording = store.get_gta_recording(recording_id) if recording_id else None
    if not script:
        store.update_gta_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress": "Missing script",
            "error": "script_id is required",
        })
        return
    if not recording or not recording.get("url"):
        store.update_gta_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress": "Missing facecam recording",
            "error": "recording_id with uploaded video is required",
        })
        return

    work = Path(tempfile.mkdtemp(prefix="gta_explainer_"))
    temps: List[Path] = []
    try:
        _progress(store, job_id, stage="validate", progress="Validating inputs…", percent=5)

        # Commercial gate on selected sources later; require at least one approved
        # gameplay segment if force_commercial flag set.
        force_commercial = bool(payload.get("require_commercial", True))

        face_suffix = suffix_from_url_or_type(recording.get("url") or "", recording.get("content_type") or "")
        facecam_path = download_to_temp(recording["url"], suffix=face_suffix)
        temps.append(facecam_path)

        _progress(store, job_id, stage="transcribe", progress="Transcribing facecam…", percent=15)
        analysis = analyze_recording(facecam_path, script)
        store.update_gta_recording(recording_id, {
            "transcript": analysis.get("transcript") or "",
            "transcript_segments": analysis.get("transcript_segments") or [],
            "alignment": analysis.get("alignment") or {},
        })

        sections = (analysis.get("alignment") or {}).get("sections") or []
        _progress(store, job_id, stage="select_gameplay", progress="Selecting gameplay…", percent=30)
        selections = select_gameplay_for_sections(
            store,
            sections,
            script.get("visual_plan") or [],
            require_commercial=force_commercial,
        )
        if force_commercial:
            bad = [s for s in selections if s.get("segment_id") and not s.get("commercial_ok")]
            missing = [s for s in selections if not s.get("segment_id")]
            if missing:
                raise ValueError(
                    "No matching gameplay in the library. Upload tagged gameplay segments first."
                )
            if bad:
                # Re-check each source; if none commercial-ok, block export
                if all(not s.get("commercial_ok") for s in selections):
                    raise ValueError(
                        "Commercial publishing blocked: approve a footage source with commercial use enabled."
                    )

        # Build a single gameplay reel covering narration duration
        _progress(store, job_id, stage="prepare_gameplay", progress="Preparing gameplay clips…", percent=45)
        face_info = media_info(facecam_path)
        face_dur = float(face_info.get("duration_sec") or script.get("target_duration_sec") or 45)

        gameplay_parts: List[Path] = []
        for i, sel in enumerate(selections):
            url = (sel.get("url") or "").strip()
            if not url and sel.get("video_id"):
                video = store.get_gta_video(sel["video_id"])
                url = (video or {}).get("url") or ""
            if not url:
                continue
            src = download_to_temp(url, suffix=suffix_from_url_or_type(url))
            temps.append(src)
            start = float(sel.get("start_sec") or 0)
            end = float(sel.get("end_sec") or 0)
            section_start = float(sel.get("section_start") or 0)
            section_end = float(sel.get("section_end") or section_start + 3)
            needed = max(1.5, section_end - section_start)
            if end <= start:
                end = start + needed
            # Cap clip length to section need (+ small pad)
            end = min(end, start + needed + 0.4)
            part = work / f"gp_{i:02d}.mp4"
            try:
                trim_clip(src, part, start, end)
                gameplay_parts.append(part)
            except Exception as e:
                logger.warning("[GTA] gameplay trim failed: %s", e)

        if not gameplay_parts:
            raise ValueError("Could not prepare any gameplay clips")

        gameplay_reel = work / "gameplay_reel.mp4"
        concat_clips(gameplay_parts, gameplay_reel)

        _progress(store, job_id, stage="compose", progress="Composing vertical layout…", percent=60)
        composed = work / "composed.mp4"
        compose_layout(
            facecam_path=facecam_path,
            gameplay_path=gameplay_reel,
            output_path=composed,
            template=template,
            duration_sec=face_dur,
        )

        cost = estimate_explainer_cost(duration_sec=face_dur, vision_images=0)
        store.update_gta_job(job_id, {"cost_estimate": cost})

        _progress(store, job_id, stage="captions", progress="Burning captions…", percent=75)
        ass_path = work / "captions.ass"
        segments_to_ass(
            analysis.get("transcript_segments") or [],
            ass_path,
            highlight_keywords=True,
        )
        captioned = work / "captioned.mp4"
        try:
            burn_subtitles(composed, ass_path, captioned)
        except Exception as e:
            logger.warning("[GTA] caption burn failed, continuing without: %s", e)
            shutil.copyfile(composed, captioned)

        current = captioned
        logo_url = (settings.get("logo_url") or "").strip()
        if logo_url:
            _progress(store, job_id, stage="branding", progress="Applying branding…", percent=82)
            logo_path = download_to_temp(logo_url, suffix=suffix_from_url_or_type(logo_url, "image/png"))
            temps.append(logo_path)
            branded = work / "branded.mp4"
            apply_branding(current, branded, logo_path=logo_path)
            current = branded

        music_url = (settings.get("music_url") or "").strip()
        if music_url:
            _progress(store, job_id, stage="music", progress="Mixing music…", percent=88)
            music_path = download_to_temp(music_url, suffix=suffix_from_url_or_type(music_url, "audio/mpeg"))
            temps.append(music_path)
            mixed = work / "mixed.mp4"
            mix_music(current, music_path, mixed, music_volume=float(settings.get("music_volume") or 0.12))
            current = mixed

        _progress(store, job_id, stage="upload", progress="Uploading export…", percent=93)
        final_path = work / "final.mp4"
        shutil.copyfile(current, final_path)
        url, filename = upload_gta_path(final_path, content_type="video/mp4", prefix="gta_explainer")
        info = media_info(final_path)

        export = store.create_gta_export({
            "name": script.get("title") or "GTA explainer",
            "pipeline": "explainer",
            "job_id": job_id,
            "script_id": script_id,
            "recording_id": recording_id,
            "url": url,
            "duration_sec": info.get("duration_sec"),
            "template": template,
            "status": "needs_review",
            "title": script.get("title") or "",
            "caption": (script.get("hook") or "")[:220],
            "gameplay_selection": selections,
            "cost_estimate": cost,
            "created_by": job.get("created_by") or "",
        })

        if settings.get("email_finished_videos") and settings.get("notify_email"):
            try:
                from app.email_notify import email_video
                email_video(
                    to_email=settings["notify_email"],
                    video_url=url,
                    video_name=export.get("title") or "GTA explainer",
                    message="Your GTA explainer is ready for review.",
                )
            except Exception as e:
                logger.warning("[GTA] email notify failed: %s", e)

        store.update_gta_job(job_id, {
            "status": "complete",
            "stage": "complete",
            "progress": "Complete — ready for review",
            "progress_percent": 100,
            "error": "",
            "completed_at": _now(),
            "cost_estimate": cost,
            "result": {
                "export_id": export.get("id"),
                "url": url,
                "filename": filename,
                "selections": selections,
            },
        })
    except Exception as e:
        logger.exception("[GTA] explainer job %s failed", job_id)
        store.update_gta_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress": "Failed",
            "error": str(e)[:800],
            "completed_at": _now(),
        })
        raise
    finally:
        for p in temps:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            shutil.rmtree(work, ignore_errors=True)
        except Exception:
            pass
