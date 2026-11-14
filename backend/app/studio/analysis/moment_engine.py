"""
High-quality viral moment discovery — rebuilt from scratch.

Design (Opus ClipAnything–style, sports-proof):
1. Collect signals: transcript, audio climaxes, motion bursts, scenes
2. AI Director reads a HUGE timed script + full briefing → proposes main_moment + others
3. Visual Climax Jury: show labeled frames from top AV peaks in ONE vision call
   and ask which timestamp is THE defining climax (this catches KOs audio misses)
4. Merge: visual jury wins for main; director fills supporting clips
5. Return a clean ordered plan — caller only windows + renders
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _client():
    from app.openai_client import get_openai_client
    return get_openai_client()


def _model() -> str:
    return os.getenv("GTA_VISION_MODEL") or os.getenv("CHAT_MODEL") or "gpt-4o"


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return json.loads(m.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("could not parse JSON")


def _script_dump(segments: List[Dict[str, Any]], *, max_chars: int = 32000) -> str:
    lines: List[str] = []
    total = 0
    for s in segments or []:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        start = float(s.get("start") or 0)
        line = f"[{int(start // 60):02d}:{int(start % 60):02d}] {text}"
        if total + len(line) + 1 > max_chars:
            lines.append("…[transcript truncated]…")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _unique_peaks(
    peaks: List[Dict[str, Any]],
    *,
    min_gap: float = 8.0,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in peaks:
        t = float(p.get("time_sec") or 0)
        if t < 0:
            continue
        if any(abs(t - float(o.get("time_sec") or 0)) < min_gap for o in out):
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return out


def collect_signal_peaks(
    *,
    audio_climaxes: List[Dict[str, Any]],
    motion_peaks: List[Dict[str, Any]],
    curve_peaks: List[Dict[str, Any]],
    limit: int = 14,
) -> List[Dict[str, Any]]:
    """Rank candidate peak times for visual jury + director hints."""
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for c in audio_climaxes or []:
        z = float(c.get("z_score") or c.get("score") or 0)
        bonus = 8.0 if c.get("global_max") else 0.0
        ranked.append((50 + z * 4 + bonus, {**c, "signal": "audio_climax"}))
    for m in motion_peaks or []:
        z = float(m.get("z_score") or m.get("score") or 0)
        # Strong motion is often the real finish even when audio peaked earlier
        ranked.append((45 + z * 6, {**m, "signal": "motion"}))
    for p in curve_peaks or []:
        z = float(p.get("z_score") or p.get("score") or 0)
        ranked.append((30 + z * 3, {**p, "signal": "audio_curve"}))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return _unique_peaks([r[1] for r in ranked], min_gap=7.0, limit=limit)


def ai_director_plan(
    *,
    segments: List[Dict[str, Any]],
    video_title: str,
    video_context: str,
    streamer_name: str,
    duration_sec: float,
    target_duration_sec: float,
    clip_count: int,
    signal_peaks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Dump full briefing + huge script into the model.
    Returns {main_moment, moments[]} or {}.
    """
    from app.studio.analysis.highlight_scoring import duration_bounds, preferred_clip_length

    lo, hi = duration_bounds(target_duration_sec)
    preferred = preferred_clip_length(target_duration_sec)
    script = _script_dump(segments, max_chars=32000 if duration_sec <= 900 else 24000)
    peaks = [
        {
            "time_sec": round(float(p.get("time_sec") or 0), 1),
            "signal": p.get("signal") or p.get("source") or p.get("kind"),
            "strength": round(float(p.get("z_score") or p.get("score") or 0), 2),
            "global_max": bool(p.get("global_max")),
        }
        for p in signal_peaks[:16]
    ]
    user_ctx = (video_context or "").strip() or (
        "Infer from the title and script what the single most important climax is."
    )
    prompt = (
        "PRODUCT\n"
        "You are the clip director for GTAClipper. The user wants viral short-form clips "
        "(TikTok / Shorts / Reels) from ONE long video. Quality bar: Opus Clip / ClipAnything.\n\n"
        "THIS VIDEO\n"
        f"- Title: {video_title or 'unknown'}\n"
        f"- Labelled as: {streamer_name or 'unknown'}\n"
        f"- Duration: {round(float(duration_sec), 1)}s\n"
        f"- User brief (what this is / what to find):\n{user_ctx}\n"
        f"- Clip length target ~{preferred:.0f}s (allowed {lo:.0f}–{hi:.0f}s)\n"
        f"- Need {clip_count} clips total; first must be THE main climax.\n\n"
        "TASK\n"
        "1) Read the FULL timed script.\n"
        "2) Decide what the story climax is for THIS video (finish, punchline, reveal, win…).\n"
        "3) Set main_moment to that climax timestamp (peak of the action, not the intro).\n"
        "4) Add other distinct high-value moments for remaining slots.\n\n"
        "RULES\n"
        "- Never invent timestamps outside the script / signal list.\n"
        "- If speech is thin, use signal_peaks (especially motion) that match the story climax.\n"
        "- Mid-video crowd noise is NOT automatically the climax — the finish/payoff is.\n"
        "- Each clip needs hook → payoff → short reaction when possible.\n\n"
        f"SIGNAL PEAKS (audio/motion detectors):\n{json.dumps(peaks, ensure_ascii=False)}\n\n"
        f"FULL TIMED SCRIPT:\n{script or '(little/no speech — rely on title, brief, and signal peaks)'}\n\n"
        "Return JSON only:\n"
        '{"main_moment":{"time_sec":0,"start_sec":0,"end_sec":20,"score":95,'
        '"title":"","caption":"","reason":"why this is THE climax"},'
        f'"moments":[{{"time_sec":0,"start_sec":0,"end_sec":20,"score":80,'
        '"title":"","caption":"","reason":""}}]}}'
    )
    try:
        resp = _client().chat.completions.create(
            model=_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Expert short-form clip director. Read the brief + full script. "
                        "Pick THE main climax first. JSON only. No invented timestamps."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("[GTA] AI director failed: %s", e)
        return {}


def visual_climax_jury(
    video_path: Path,
    *,
    candidate_peaks: List[Dict[str, Any]],
    video_title: str,
    video_context: str,
    streamer_name: str,
    duration_sec: float,
    work_dir: Path,
) -> Optional[Dict[str, Any]]:
    """
    Show the model labeled stills from each candidate peak and ask which is
    THE defining climax. This is how we catch knockouts that aren't the loudest.
    """
    from app.studio.analysis.frames import extract_frame, frame_to_data_url
    from app.studio.analysis.highlight_scoring import clean_caption_text

    peaks = _unique_peaks(candidate_peaks, min_gap=6.0, limit=10)
    if len(peaks) < 2:
        return None

    work_dir.mkdir(parents=True, exist_ok=True)
    content: List[Dict[str, Any]] = []
    user_ctx = (video_context or "").strip() or "Infer the defining climax from title + frames."
    content.append({
        "type": "text",
        "text": (
            "You are judging which moment is THE climax of this video for a viral short.\n\n"
            f"Title: {video_title or 'unknown'}\n"
            f"Creator label: {streamer_name or 'unknown'}\n"
            f"Duration: {round(float(duration_sec), 1)}s\n"
            f"User brief: {user_ctx}\n\n"
            "Below are still frames from detector peak times (BEFORE isn't shown — each image "
            "is the peak candidate). Pick the ONE timestamp that is the true finish / payoff / "
            "most shareable climax (e.g. knockout, crash, celebration, punchline reaction).\n"
            "Do NOT pick a neutral mid-fight stance, intro graphic, or outro slate if a real "
            "finish frame exists.\n"
            "Return JSON only: "
            '{"time_sec":0,"score":0-100,"title":"","caption":"","reason":"why this frame is the climax"}'
        ),
    })

    labeled: List[float] = []
    for i, p in enumerate(peaks):
        t = float(p.get("time_sec") or 0)
        # Also grab a reaction beat +0.8s for action finishes
        for j, tt in enumerate([t, min(duration_sec - 0.05, t + 0.9)]):
            path = work_dir / f"jury_{i}_{j}_{int(tt * 10)}.jpg"
            got = extract_frame(video_path, tt, path, width=512)
            if not got:
                continue
            tag = f"CANDIDATE {i + 1} @ {t:.1f}s ({p.get('signal') or p.get('source') or 'peak'})"
            if j == 1:
                tag += " [+0.9s reaction]"
            content.append({"type": "text", "text": tag})
            content.append({
                "type": "image_url",
                "image_url": {"url": frame_to_data_url(got), "detail": "low"},
            })
            labeled.append(t)

    if len(set(round(t, 1) for t in labeled)) < 2:
        return None

    try:
        resp = _client().chat.completions.create(
            model=_model(),
            messages=[{"role": "user", "content": content}],
            temperature=0.1,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if not isinstance(data, dict):
            return None
        t = float(data.get("time_sec") or 0)
        if t <= 0 or t > duration_sec + 1:
            return None
        # Snap to nearest candidate peak (model sometimes drifts a second)
        nearest = min(peaks, key=lambda p: abs(float(p.get("time_sec") or 0) - t))
        snap_t = float(nearest.get("time_sec") or t)
        if abs(snap_t - t) <= 6.0:
            t = snap_t
        return {
            "time_sec": round(t, 2),
            "score": 2.2,
            "kind": "visual_climax",
            "source": "visual_jury",
            "weight": 4.0,
            "climax": True,
            "is_main": True,
            "gpt_main": True,
            "reserved": True,
            "title": clean_caption_text(data.get("title") or "") or "Main climax",
            "caption": clean_caption_text(data.get("caption") or ""),
            "reason": (data.get("reason") or "visual climax jury").strip(),
            "virality_score": float(data.get("score") or 96),
        }
    except Exception as e:
        logger.warning("[GTA] visual climax jury failed: %s", e)
        return None


def _normalize_moment(
    m: Dict[str, Any],
    *,
    duration_sec: float,
    target_duration_sec: float,
    is_main: bool = False,
) -> Optional[Dict[str, Any]]:
    from app.studio.analysis.highlight_scoring import (
        clamp_window_to_target,
        clean_caption_text,
        preferred_clip_length,
    )

    if not isinstance(m, dict):
        return None
    t = float(m.get("time_sec") or m.get("start_sec") or 0)
    if t < 0 or t > duration_sec + 1:
        return None
    preferred = preferred_clip_length(target_duration_sec)
    start = m.get("start_sec")
    end = m.get("end_sec")
    if start is None or end is None:
        start = max(0.0, t - preferred * 0.38)
        end = min(duration_sec, start + preferred)
    else:
        start = float(start)
        end = float(end)
    start, end = clamp_window_to_target(
        float(start),
        float(end),
        duration_sec=duration_sec,
        target_duration_sec=float(target_duration_sec),
        peak_sec=t,
        prefer_story=True,
    )
    raw = float(m.get("score") or m.get("virality_score") or (96 if is_main else 70))
    if raw <= 5:
        raw = min(100.0, raw * 45.0)
    return {
        "time_sec": round(t, 2),
        "start_sec": start,
        "end_sec": end,
        "title": clean_caption_text(m.get("title") or "") or ("Main climax" if is_main else "Highlight"),
        "caption": clean_caption_text(m.get("caption") or ""),
        "reason": (m.get("reason") or "").strip(),
        "hook": (m.get("hook") or "").strip(),
        "payoff": (m.get("payoff") or "").strip(),
        "score": max(raw, 96.0 if is_main else raw),
        "virality_score": max(raw, 96.0 if is_main else raw),
        "composite_score": max(raw, 96.0 if is_main else raw),
        "is_main": is_main,
        "climax": True if is_main else bool(raw >= 85),
        "reserved": True if is_main else bool(m.get("reserved")),
        "gpt_main": is_main,
        "source": m.get("source") or ("visual_jury" if is_main else "gpt_transcript"),
        "sources": list(m.get("sources") or [m.get("source") or "moment_engine"]),
        "kinds": list(m.get("kinds") or [m.get("kind") or "climax"]),
        "entertaining": True,
    }


def discover_moments(
    video_path: Path,
    *,
    segments: List[Dict[str, Any]],
    duration_sec: float,
    target_duration_sec: float,
    clip_count: int,
    video_title: str = "",
    video_context: str = "",
    streamer_name: str = "",
    audio_pack: Optional[Dict[str, Any]] = None,
    motion_peaks: Optional[List[Dict[str, Any]]] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Full discovery. Returns:
      {
        main: moment dict,
        moments: [moment dicts]  # includes main first, then others, de-duped
        signal_peaks: [...]
      }
    """
    from app.studio.analysis.audio_analysis import analyze_audio_highlights
    from app.studio.analysis.motion_analysis import detect_motion_peaks

    work = work_dir or (video_path.parent / "_moment_engine")
    work.mkdir(parents=True, exist_ok=True)

    if audio_pack is None:
        audio_pack = analyze_audio_highlights(
            video_path,
            spike_top_n=max(20, clip_count * 3),
            jump_top_n=max(12, clip_count * 2),
            climax_top_n=max(10, clip_count + 3),
        )
    if motion_peaks is None:
        try:
            motion_peaks = detect_motion_peaks(video_path, top_n=max(14, clip_count * 3))
        except Exception as e:
            logger.warning("[GTA] motion failed: %s", e)
            motion_peaks = []

    climaxes = audio_pack.get("climaxes") or []
    curves = audio_pack.get("curve_peaks") or []
    silences = audio_pack.get("silences") or []
    signal_peaks = collect_signal_peaks(
        audio_climaxes=climaxes,
        motion_peaks=motion_peaks or [],
        curve_peaks=curves,
        limit=14,
    )

    # 1) Visual jury FIRST — decides THE climax from actual frames
    jury = visual_climax_jury(
        video_path,
        candidate_peaks=signal_peaks,
        video_title=video_title,
        video_context=video_context,
        streamer_name=streamer_name,
        duration_sec=duration_sec,
        work_dir=work / "jury",
    )

    # 2) Script director for main (fallback) + supporting moments
    plan = ai_director_plan(
        segments=segments,
        video_title=video_title,
        video_context=video_context,
        streamer_name=streamer_name,
        duration_sec=duration_sec,
        target_duration_sec=target_duration_sec,
        clip_count=clip_count,
        signal_peaks=signal_peaks,
    )

    main_raw = jury or plan.get("main_moment") or {}
    if not main_raw and signal_peaks:
        # Last resort: strongest motion, else global audio
        motion_first = [p for p in signal_peaks if p.get("signal") == "motion"]
        pick = (motion_first[0] if motion_first else signal_peaks[0])
        main_raw = {
            **pick,
            "title": "Peak moment",
            "caption": "",
            "reason": "fallback signal peak",
            "score": 90,
        }

    main = _normalize_moment(
        main_raw,
        duration_sec=duration_sec,
        target_duration_sec=target_duration_sec,
        is_main=True,
    )

    others: List[Dict[str, Any]] = []
    for m in (plan.get("moments") or []):
        packed = _normalize_moment(
            m,
            duration_sec=duration_sec,
            target_duration_sec=target_duration_sec,
            is_main=False,
        )
        if not packed:
            continue
        if main and abs(float(packed["time_sec"]) - float(main["time_sec"])) < 10:
            continue
        others.append(packed)

    # Ensure strong signal peaks also appear as candidates if director under-picked
    for p in signal_peaks[: max(6, clip_count + 2)]:
        t = float(p.get("time_sec") or 0)
        if main and abs(t - float(main["time_sec"])) < 10:
            continue
        if any(abs(t - float(o["time_sec"])) < 10 for o in others):
            continue
        packed = _normalize_moment(
            {
                **p,
                "title": f"{streamer_name or 'Highlight'} moment",
                "caption": "",
                "reason": f"signal:{p.get('signal')}",
                "score": 78,
            },
            duration_sec=duration_sec,
            target_duration_sec=target_duration_sec,
            is_main=False,
        )
        if packed:
            others.append(packed)

    moments: List[Dict[str, Any]] = []
    if main:
        moments.append(main)
    moments.extend(others)

    # De-dupe + cap
    final: List[Dict[str, Any]] = []
    for m in moments:
        t = float(m.get("time_sec") or 0)
        if any(abs(t - float(x.get("time_sec") or 0)) < 10 for x in final):
            continue
        final.append(m)
        if len(final) >= max(clip_count + 2, clip_count):
            break

    logger.info(
        "[GTA] moment_engine main=%.1fs source=%s (+%d more)",
        float((main or {}).get("time_sec") or 0),
        (main or {}).get("source"),
        max(0, len(final) - 1),
    )
    return {
        "main": main,
        "moments": final,
        "signal_peaks": signal_peaks,
        "silences": silences,
        "audio_pack": audio_pack,
        "motion_peaks": motion_peaks or [],
    }
