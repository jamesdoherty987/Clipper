"""Full streamer clipping pipeline: analyse → score → render vertical shorts."""
from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.studio.analysis.audio_analysis import detect_audio_spikes
from app.studio.analysis.frames import extract_frames
from app.studio.analysis.highlight_scoring import (
    gpt_rank_clips,
    merge_candidates,
    transcript_reaction_peaks,
)
from app.studio.analysis.scene_detection import detect_scene_changes
from app.studio.analysis.vision import analyze_highlight_moment
from app.studio.costing import estimate_clip_job_cost
from app.studio.storage import download_to_temp, suffix_from_url_or_type
from app.studio.streamer_clips.clip_generation import render_streamer_clip
from app.studio.transcription import transcribe_audio
from app.studio.video_engine.ffmpeg import ffmpeg_available, media_info

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _progress(store, job_id: str, *, stage: str, progress: str, percent: int, **extra):
    store.update_gta_job(job_id, {
        "status": "processing",
        "stage": stage,
        "progress": progress,
        "progress_percent": max(0, min(100, int(percent))),
        **extra,
    })


def _transcript_near(segments: List[Dict[str, Any]], time_sec: float, window: float = 8.0) -> str:
    bits = []
    for s in segments or []:
        start = float(s.get("start") or 0)
        end = float(s.get("end") or start)
        if end < time_sec - window or start > time_sec + window:
            continue
        bits.append((s.get("text") or "").strip())
    return " ".join(bits).strip()


def _window_for_candidate(
    c: Dict[str, Any],
    *,
    duration_sec: float,
    target_duration_sec: float,
) -> tuple[float, float]:
    center = float(c.get("time_sec") or 0)
    start_off = float(c.get("good_start_offset_sec") if c.get("good_start_offset_sec") is not None else -5)
    end_off = float(c.get("good_end_offset_sec") if c.get("good_end_offset_sec") is not None else max(12, target_duration_sec - 5))
    start = max(0.0, center + start_off)
    end = min(duration_sec, center + end_off)
    # Enforce roughly target length with context padding
    if end - start < target_duration_sec * 0.7:
        pad = (target_duration_sec - (end - start)) / 2
        start = max(0.0, start - pad)
        end = min(duration_sec, end + pad)
    if end - start > target_duration_sec * 1.35:
        end = start + target_duration_sec
    if end <= start + 3:
        end = min(duration_sec, start + max(8.0, target_duration_sec * 0.75))
    return round(start, 2), round(end, 2)


def start_clip_job(store, job_id: str) -> None:
    job = store.get_gta_job(job_id)
    if not job:
        return
    payload = dict(job.get("payload") or {})
    video_id = (payload.get("video_id") or "").strip()
    clip_count = max(1, min(20, int(payload.get("clip_count") or 8)))
    target_duration = max(12, min(75, int(payload.get("target_duration_sec") or 30)))
    template = (payload.get("template") or "fullscreen_gameplay").strip()
    streamer_name = (payload.get("streamer_name") or "").strip()
    settings = store.get_gta_settings()

    work = Path(tempfile.mkdtemp(prefix="gta_clips_"))
    temps: List[Path] = []
    try:
        if not ffmpeg_available():
            raise RuntimeError("ffmpeg/ffprobe must be installed on PATH")
        video = store.get_gta_video(video_id) if video_id else None
        if not video or not video.get("url"):
            raise ValueError("Source video not found")
        if not streamer_name:
            streamer_name = (video.get("streamer_name") or "Streamer").strip()

        # Rights gate when source attached
        source_id = (payload.get("source_id") or video.get("source_id") or "").strip()
        if source_id:
            store.assert_gta_source_commercial_ok(source_id)

        _progress(store, job_id, stage="download", progress="Downloading source video…", percent=5)
        src = download_to_temp(
            video["url"],
            suffix=suffix_from_url_or_type(video.get("url") or "", video.get("content_type") or ""),
        )
        temps.append(src)
        info = media_info(src)
        duration = float(info.get("duration_sec") or 0)
        if duration <= 0:
            raise ValueError("Could not read source duration")

        cost = estimate_clip_job_cost(
            duration_sec=duration,
            clip_count=clip_count,
            vision_candidates=min(18, clip_count * 2 + 4),
        )
        store.update_gta_job(job_id, {"cost_estimate": cost})

        _progress(store, job_id, stage="transcribe", progress="Transcribing audio…", percent=14)
        transcript = {"text": "", "segments": []}
        try:
            transcript = transcribe_audio(src)
        except Exception as e:
            logger.warning("[GTA] transcription failed, continuing: %s", e)

        _progress(store, job_id, stage="audio", progress="Detecting excitement spikes…", percent=26)
        audio = detect_audio_spikes(src, top_n=max(20, clip_count * 3))

        _progress(store, job_id, stage="scenes", progress="Detecting scene changes…", percent=34)
        scenes = detect_scene_changes(src)

        tx_peaks = transcript_reaction_peaks(transcript.get("segments") or [])
        candidates = merge_candidates(
            audio=audio,
            scenes=scenes,
            transcript_peaks=tx_peaks,
            duration_sec=duration,
            max_candidates=max(16, clip_count * 3),
        )
        if not candidates:
            # Fallback evenly spaced windows
            step = max(target_duration, duration / max(clip_count, 1))
            candidates = [{"time_sec": round(min(duration - 5, i * step + 5), 2), "score": 0.3, "kinds": ["fallback"], "sources": ["fallback"]} for i in range(clip_count)]

        _progress(
            store, job_id,
            stage="vision",
            progress=f"Analysing {min(len(candidates), clip_count * 2 + 2)} moments…",
            percent=42,
        )
        visioned: List[Dict[str, Any]] = []
        analyze_n = min(len(candidates), max(clip_count * 2, 10))
        frame_dir = work / "cand_frames"
        for i, cand in enumerate(candidates[:analyze_n]):
            t = float(cand.get("time_sec") or 0)
            frame_times = [max(0, t - 1.2), t, min(duration - 0.1, t + 1.5)]
            frames = extract_frames(src, frame_times, frame_dir / f"c{i}", prefix="c")
            snip = _transcript_near(transcript.get("segments") or [], t)
            kinds = cand.get("kinds") or []
            try:
                judgment = analyze_highlight_moment(
                    frames,
                    time_sec=t,
                    transcript_snip=snip,
                    audio_kind=",".join([k for k in kinds if k])[:80],
                )
            except Exception as e:
                logger.warning("[GTA] vision highlight failed: %s", e)
                judgment = {
                    "entertaining": True,
                    "score": float(cand.get("score") or 40),
                    "summary": snip[:120] or "Candidate moment",
                    "title": f"{streamer_name} moment",
                    "caption": snip[:160],
                    "good_start_offset_sec": -5,
                    "good_end_offset_sec": target_duration - 5,
                    "needs_facecam": True,
                    "reason": "vision_fallback",
                }
            start, end = _window_for_candidate(
                {**cand, **judgment},
                duration_sec=duration,
                target_duration_sec=float(target_duration),
            )
            visioned.append({
                **cand,
                **judgment,
                "vision_score": float(judgment.get("score") or 0),
                "vision_summary": judgment.get("summary") or "",
                "start_sec": start,
                "end_sec": end,
                "transcript_snip": snip,
            })
            pct = 42 + int(20 * ((i + 1) / max(1, analyze_n)))
            _progress(
                store, job_id,
                stage="vision",
                progress=f"Vision {i + 1}/{analyze_n}…",
                percent=pct,
            )

        _progress(store, job_id, stage="rank", progress="Ranking best clips…", percent=68)
        ranked = gpt_rank_clips(
            visioned,
            streamer_name=streamer_name,
            target_count=clip_count,
            target_duration_sec=target_duration,
        )
        # Merge titles back from vision where GPT omitted them
        by_time = {round(float(v.get("time_sec") or 0), 1): v for v in visioned}
        final_windows = []
        for r in ranked:
            key = round(float(r.get("time_sec") or 0), 1)
            base = by_time.get(key) or {}
            start = float(r.get("start_sec") or base.get("start_sec") or 0)
            end = float(r.get("end_sec") or base.get("end_sec") or start + target_duration)
            if end <= start:
                start, end = _window_for_candidate(base or r, duration_sec=duration, target_duration_sec=float(target_duration))
            final_windows.append({
                **base,
                **r,
                "start_sec": start,
                "end_sec": min(duration, end),
                "title": (r.get("title") or base.get("title") or f"{streamer_name} highlight").strip(),
                "caption": (r.get("caption") or base.get("caption") or base.get("summary") or "").strip(),
                "score": float(r.get("score") or base.get("vision_score") or 0),
                "transcript_snip": base.get("transcript_snip") or "",
            })

        # Branding assets
        logo_path = None
        music_path = None
        if settings.get("logo_url"):
            try:
                logo_path = download_to_temp(settings["logo_url"], suffix=".png")
                temps.append(logo_path)
            except Exception:
                logo_path = None
        if settings.get("music_url"):
            try:
                music_path = download_to_temp(settings["music_url"], suffix=".mp3")
                temps.append(music_path)
            except Exception:
                music_path = None

        created_ids: List[str] = []
        for i, win in enumerate(final_windows):
            _progress(
                store, job_id,
                stage="render",
                progress=f"Rendering clip {i + 1}/{len(final_windows)}…",
                percent=72 + int(22 * ((i + 1) / max(1, len(final_windows)))),
            )
            start = float(win.get("start_sec") or 0)
            end = float(win.get("end_sec") or start + target_duration)
            # Captions overlapping this window
            caps = []
            for s in transcript.get("segments") or []:
                s0 = float(s.get("start") or 0)
                s1 = float(s.get("end") or s0)
                if s1 < start or s0 > end:
                    continue
                caps.append(s)
            try:
                rendered = render_streamer_clip(
                    src,
                    start_sec=start,
                    end_sec=end,
                    caption_segments=caps,
                    template=template,
                    apply_zoom=True,
                    logo_path=logo_path,
                    music_path=music_path,
                    music_volume=float(settings.get("music_volume") or 0.1),
                )
            except Exception as e:
                logger.warning("[GTA] clip render failed: %s", e)
                continue

            clip = store.create_gta_clip({
                "job_id": job_id,
                "video_id": video_id,
                "title": win.get("title") or f"{streamer_name} clip {i + 1}",
                "caption": win.get("caption") or "",
                "url": rendered.get("url") or "",
                "duration_sec": rendered.get("duration_sec"),
                "score": round(float(win.get("score") or 0), 1),
                "source_start_sec": start,
                "source_end_sec": end,
                "template": template,
                "reason": win.get("reason") or win.get("summary") or "",
                "transcript_snip": win.get("transcript_snip") or "",
                "status": "pending",
            })
            created_ids.append(clip["id"])

            # Also surface in exports review list
            store.create_gta_export({
                "name": clip.get("title") or "Streamer clip",
                "pipeline": "streamer_clip",
                "job_id": job_id,
                "url": clip.get("url") or "",
                "duration_sec": clip.get("duration_sec"),
                "template": template,
                "status": "needs_review",
                "title": clip.get("title") or "",
                "caption": clip.get("caption") or "",
                "score": clip.get("score"),
                "source_timestamp": f"{start:.1f}s–{end:.1f}s",
                "cost_estimate": cost,
                "created_by": job.get("created_by") or "",
            })

        if not created_ids:
            raise ValueError("No clips could be rendered from this source")

        # Optional email
        if settings.get("email_finished_videos") and settings.get("notify_email"):
            try:
                from app.email_notify import email_video
                first = store.list_gta_studio().get("clips") or []
                first = next((c for c in first if c.get("id") in created_ids and c.get("url")), None)
                if first:
                    email_video(
                        to_email=settings["notify_email"],
                        video_url=first["url"],
                        video_name=f"{streamer_name} clips ready ({len(created_ids)})",
                        message=f"{len(created_ids)} clips are ready for review in GTA Content Studio.",
                    )
            except Exception as e:
                logger.warning("[GTA] email notify failed: %s", e)

        store.update_gta_job(job_id, {
            "status": "complete",
            "stage": "complete",
            "progress": f"Created {len(created_ids)} clips",
            "progress_percent": 100,
            "completed_at": _now(),
            "cost_estimate": cost,
            "result": {
                "clip_ids": created_ids,
                "clip_count": len(created_ids),
                "duration_sec": duration,
                "candidates": len(candidates),
                "analyzed": len(visioned),
            },
        })
    except Exception as e:
        logger.exception("[GTA] clip job failed")
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
        shutil.rmtree(work, ignore_errors=True)


def regenerate_clip(store, clip_id: str, *, start_sec: float, end_sec: float, template: str = "") -> Dict[str, Any]:
    """Re-cut an existing clip with new timestamps."""
    clip = None
    for c in store.list_gta_studio().get("clips") or []:
        if c.get("id") == clip_id:
            clip = c
            break
    if not clip:
        raise ValueError("Clip not found")
    video = store.get_gta_video(clip.get("video_id") or "")
    if not video or not video.get("url"):
        raise ValueError("Source video missing")
    settings = store.get_gta_settings()
    src = download_to_temp(
        video["url"],
        suffix=suffix_from_url_or_type(video.get("url") or "", video.get("content_type") or ""),
    )
    try:
        logo_path = None
        music_path = None
        if settings.get("logo_url"):
            try:
                logo_path = download_to_temp(settings["logo_url"], suffix=".png")
            except Exception:
                pass
        rendered = render_streamer_clip(
            src,
            start_sec=float(start_sec),
            end_sec=float(end_sec),
            caption_segments=None,
            template=template or clip.get("template") or "fullscreen_gameplay",
            apply_zoom=True,
            logo_path=logo_path,
            music_path=music_path,
            music_volume=float(settings.get("music_volume") or 0.1),
        )
        updated = store.update_gta_clip(clip_id, {
            "url": rendered.get("url") or "",
            "duration_sec": rendered.get("duration_sec"),
            "source_start_sec": float(start_sec),
            "source_end_sec": float(end_sec),
            "template": template or clip.get("template") or "fullscreen_gameplay",
            "status": "pending",
        })
        return updated or clip
    finally:
        try:
            src.unlink(missing_ok=True)
        except Exception:
            pass
