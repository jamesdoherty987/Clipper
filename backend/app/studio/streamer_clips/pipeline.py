"""Full streamer clipping pipeline: discover → confirm → render vertical shorts."""
from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.studio.analysis.frames import extract_frames
from app.studio.analysis.highlight_scoring import (
    amplify_virality_scores,
    captions_for_window,
    clamp_window_to_target,
    clean_caption_text,
    coerce_virality_score,
    snap_window_to_silence,
)
from app.studio.analysis.moment_engine import discover_moments
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


def _transcript_near(segments: List[Dict[str, Any]], time_sec: float, window: float = 14.0) -> str:
    bits = []
    for s in segments or []:
        start = float(s.get("start") or 0)
        end = float(s.get("end") or start)
        if end < time_sec - window or start > time_sec + window:
            continue
        bits.append((s.get("text") or "").strip())
    return " ".join(bits).strip()


def start_clip_job(store, job_id: str) -> None:
    job = store.get_gta_job(job_id)
    if not job:
        return
    payload = dict(job.get("payload") or {})
    video_id = (payload.get("video_id") or "").strip()
    clip_count = max(1, min(20, int(payload.get("clip_count") or 8)))
    target_duration = max(8, min(120, int(payload.get("target_duration_sec") or 30)))
    streamer_name = (payload.get("streamer_name") or "").strip()
    video_context = (payload.get("video_context") or payload.get("context") or "").strip()
    from app.studio.streamer_clips.clip_style import normalize_clip_style
    style = normalize_clip_style(payload.get("style") or payload)
    template = style["template"]
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
        video_title = (video.get("name") or "").strip()
        if not video_context:
            video_context = (
                f"{video_title}. Find the single most important climax / finish / payoff "
                "of this video for a viral short — not intros or filler."
            )

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
            vision_candidates=min(28, clip_count * 3 + 4),
        )
        store.update_gta_job(job_id, {"cost_estimate": cost})

        _progress(store, job_id, stage="transcribe", progress="Transcribing full audio…", percent=12)
        transcript = {"text": "", "segments": []}
        try:
            transcript = transcribe_audio(src)
        except Exception as e:
            logger.warning("[GTA] transcription failed, continuing: %s", e)
        segments = transcript.get("segments") or []

        _progress(
            store, job_id,
            stage="discover",
            progress="Finding climax (visual jury + full script director)…",
            percent=28,
        )
        discovery = discover_moments(
            src,
            segments=segments,
            duration_sec=duration,
            target_duration_sec=float(target_duration),
            clip_count=clip_count,
            video_title=video_title,
            video_context=video_context,
            streamer_name=streamer_name,
            work_dir=work / "discover",
        )
        plan = list(discovery.get("moments") or [])
        silences = discovery.get("silences") or []
        main = discovery.get("main")
        if main:
            logger.info(
                "[GTA] MAIN CLIMAX @ %.1fs via %s — %s",
                float(main.get("time_sec") or 0),
                main.get("source"),
                (main.get("reason") or "")[:140],
            )
        if not plan:
            raise ValueError("Moment engine returned no clip candidates")

        # Take main + enough extras, then polish each with a quick vision pass
        plan = plan[: max(clip_count + 2, clip_count)]
        _progress(
            store, job_id,
            stage="vision",
            progress=f"Polishing {len(plan)} moments with vision…",
            percent=48,
        )
        polished: List[Dict[str, Any]] = []
        frame_dir = work / "frames"
        for i, mom in enumerate(plan):
            t = float(mom.get("time_sec") or 0)
            frame_times = [
                max(0, t - 2.2),
                t,
                min(duration - 0.05, t + 1.5),
                min(duration - 0.05, t + 3.2),
            ]
            frames = extract_frames(src, frame_times, frame_dir / f"m{i}", prefix="m")
            snip = clean_caption_text(_transcript_near(segments, t, window=20.0))
            try:
                judgment = analyze_highlight_moment(
                    frames,
                    time_sec=t,
                    transcript_snip=snip,
                    audio_kind=",".join(str(k) for k in (mom.get("kinds") or []) if k)[:80],
                    video_title=video_title,
                    video_context=video_context,
                    streamer_name=streamer_name,
                    frame_roles=[
                        "BEFORE (setup)",
                        "PEAK (impact)",
                        "AFTER (reaction)",
                        "AFTER+ (aftermath)",
                    ][: len(frames)],
                )
            except Exception as e:
                logger.warning("[GTA] vision polish failed: %s", e)
                judgment = {
                    "entertaining": True,
                    "score": coerce_virality_score(mom.get("score"), 80),
                    "virality_score": coerce_virality_score(mom.get("score"), 80),
                    "summary": snip[:160],
                    "title": mom.get("title") or f"{streamer_name} highlight",
                    "caption": mom.get("caption") or snip[:120],
                    "reason": mom.get("reason") or "vision_fallback",
                    "good_start_offset_sec": -6,
                    "good_end_offset_sec": max(8, int(target_duration * 0.65)),
                }

            # Main climax is never dropped for "not entertaining"
            is_main = bool(mom.get("is_main") or mom.get("gpt_main"))
            if is_main:
                judgment["entertaining"] = True
                judgment["virality_score"] = max(
                    coerce_virality_score(judgment.get("virality_score"), judgment.get("score")),
                    94.0,
                )
                judgment["score"] = judgment["virality_score"]

            start = float(mom.get("start_sec") or max(0, t - target_duration * 0.38))
            end = float(mom.get("end_sec") or start + target_duration)
            # Prefer vision offsets when present
            if judgment.get("good_start_offset_sec") is not None:
                start = max(0.0, t + float(judgment["good_start_offset_sec"]))
            if judgment.get("good_end_offset_sec") is not None:
                end = min(duration, t + float(judgment["good_end_offset_sec"]))
            start, end = clamp_window_to_target(
                start, end,
                duration_sec=duration,
                target_duration_sec=float(target_duration),
                peak_sec=t,
                prefer_story=True,
            )
            start, end = snap_window_to_silence(
                start, end, silences,
                duration_sec=duration,
                peak_sec=t,
            )
            start, end = clamp_window_to_target(
                start, end,
                duration_sec=duration,
                target_duration_sec=float(target_duration),
                peak_sec=t,
                prefer_story=True,
            )

            score = coerce_virality_score(
                judgment.get("virality_score"),
                judgment.get("score"),
                mom.get("score"),
            )
            if is_main:
                score = max(score, 96.0)

            polished.append({
                **mom,
                **judgment,
                "time_sec": t,
                "start_sec": start,
                "end_sec": min(duration, end),
                "title": clean_caption_text(
                    judgment.get("title") or mom.get("title") or ""
                ) or f"{streamer_name} highlight",
                "caption": clean_caption_text(
                    judgment.get("caption") or mom.get("caption") or snip or ""
                ),
                "transcript_snip": snip or clean_caption_text(mom.get("text") or ""),
                "score": score,
                "virality_score": score,
                "composite_score": score,
                "is_main": is_main,
                "climax": is_main or bool(mom.get("climax")),
                "reason": (
                    judgment.get("reason") or mom.get("reason") or ""
                ).strip(),
            })
            _progress(
                store, job_id,
                stage="vision",
                progress=f"Vision {i + 1}/{len(plan)}…",
                percent=48 + int(18 * ((i + 1) / max(1, len(plan)))),
            )

        # Final set: main first, then best others (no soft filters that drop the KO)
        main_rows = [p for p in polished if p.get("is_main")]
        rest = [p for p in polished if not p.get("is_main")]
        rest.sort(
            key=lambda x: coerce_virality_score(x.get("score"), x.get("virality_score")),
            reverse=True,
        )
        final_windows: List[Dict[str, Any]] = []
        used: List[float] = []
        for row in main_rows + rest:
            t = float(row.get("time_sec") or 0)
            if any(abs(t - u) < 12 for u in used):
                continue
            final_windows.append(row)
            used.append(t)
            if len(final_windows) >= clip_count:
                break

        if not final_windows:
            raise ValueError("No polished moments available to render")

        # Guarantee main is present even if overlap logic somehow skipped it
        if main_rows:
            mt = float(main_rows[0].get("time_sec") or 0)
            if not any(abs(float(w.get("time_sec") or 0) - mt) < 12 for w in final_windows):
                final_windows = [main_rows[0]] + final_windows
                final_windows = final_windows[:clip_count]

        final_windows.sort(
            key=lambda x: (
                1 if x.get("is_main") else 0,
                coerce_virality_score(x.get("score"), x.get("virality_score")),
            ),
            reverse=True,
        )
        final_windows = amplify_virality_scores(final_windows[:clip_count])

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
            end = float(win.get("end_sec") or 0)
            start, end = clamp_window_to_target(
                start, end,
                duration_sec=duration,
                target_duration_sec=float(target_duration),
                peak_sec=float(win.get("time_sec") or ((start + end) / 2)),
                prefer_story=True,
            )
            caps = captions_for_window(
                segments,
                start=start,
                end=end,
                fallback_texts=[
                    win.get("transcript_snip") or "",
                    win.get("caption") or "",
                    win.get("hook") or "",
                ],
            ) if style.get("burn_captions") else []
            try:
                rendered = render_streamer_clip(
                    src,
                    start_sec=start,
                    end_sec=end,
                    caption_segments=caps or None,
                    template=template,
                    logo_path=logo_path if style.get("show_logo") else None,
                    music_path=music_path if style.get("use_music") else None,
                    music_volume=float(
                        style["music_volume"]
                        if style.get("music_volume") is not None
                        else (settings.get("music_volume") or 0.1)
                    ),
                    intro_title=(
                        style.get("intro_text")
                        or win.get("title")
                        or f"{streamer_name} highlight"
                    ).strip(),
                    intro_subtitle=(streamer_name or settings.get("channel_name") or "").strip(),
                    style=style,
                    brand_color=(settings.get("brand_color") or "#22c55e"),
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
                "score": round(coerce_virality_score(win.get("score"), win.get("virality_score")), 1),
                "source_start_sec": start,
                "source_end_sec": end,
                "template": template,
                "reason": win.get("reason") or win.get("summary") or "",
                "transcript_snip": win.get("transcript_snip") or "",
                "is_main": bool(win.get("is_main")),
                "status": "pending",
            })
            created_ids.append(clip["id"])
            store.create_gta_export({
                "name": clip.get("title") or "Streamer clip",
                "pipeline": "streamer_clip",
                "job_id": job_id,
                "clip_id": clip.get("id") or "",
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
                "main_time_sec": float((main or {}).get("time_sec") or 0) or None,
                "main_source": (main or {}).get("source"),
                "main_reason": ((main or {}).get("reason") or "")[:240],
                "candidates": len(plan),
                "analyzed": len(polished),
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
        from app.studio.streamer_clips.clip_style import normalize_clip_style
        regen_style = normalize_clip_style({
            "template": template or clip.get("template") or "fullscreen_gameplay",
            "burn_captions": False,
            "add_intro": False,
            "add_end_card": False,
            "show_logo": bool(logo_path),
            "use_music": bool(music_path),
        })
        rendered = render_streamer_clip(
            src,
            start_sec=float(start_sec),
            end_sec=float(end_sec),
            caption_segments=None,
            logo_path=logo_path if regen_style.get("show_logo") else None,
            music_path=music_path if regen_style.get("use_music") else None,
            music_volume=float(settings.get("music_volume") or 0.1),
            style=regen_style,
            brand_color=(settings.get("brand_color") or "#22c55e"),
        )
        updated = store.update_gta_clip(clip_id, {
            "url": rendered.get("url") or "",
            "duration_sec": rendered.get("duration_sec"),
            "source_start_sec": float(start_sec),
            "source_end_sec": float(end_sec),
            "template": template or clip.get("template") or "fullscreen_gameplay",
            "status": "pending",
        })

        def _sync_exports(data):
            for exp in data.get("gta_exports") or []:
                if exp.get("clip_id") == clip_id or (
                    exp.get("job_id") == clip.get("job_id")
                    and exp.get("title") == clip.get("title")
                ):
                    exp["url"] = rendered.get("url") or exp.get("url") or ""
                    exp["duration_sec"] = rendered.get("duration_sec")
                    exp["template"] = template or clip.get("template") or "fullscreen_gameplay"
                    exp["status"] = "needs_review"
                    exp["source_timestamp"] = f"{float(start_sec):.1f}s–{float(end_sec):.1f}s"
                    exp["updated_at"] = _now()

        store.mutate(_sync_exports)
        return updated or clip
    finally:
        try:
            src.unlink(missing_ok=True)
        except Exception:
            pass
