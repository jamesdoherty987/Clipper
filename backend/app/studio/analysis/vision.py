"""Vision model helpers for gameplay understanding and highlight context."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.studio.analysis.frames import frame_to_data_url

logger = logging.getLogger(__name__)


def _model() -> str:
    return os.getenv("GTA_VISION_MODEL") or os.getenv("CHAT_MODEL") or "gpt-4o"


def _client():
    from app.openai_client import get_openai_client

    return get_openai_client()


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty vision response")
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
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("could not parse vision JSON")


def describe_gameplay_frame(frame_path: Path, *, context: str = "") -> Dict[str, Any]:
    client = _client()
    data_url = frame_to_data_url(frame_path)
    prompt = (
        "Describe this GTA / open-world gameplay frame for a footage library. "
        "Be concrete. Return JSON only: "
        '{"description":"","tags":["police","chase"],"action_level":1-5,'
        '"setting":"city|highway|beach|interior|rural|other","has_vehicles":true,'
        '"has_police":false,"has_explosion":false,"suitable_broll":true}'
    )
    if context:
        prompt += f"\nContext: {context}"
    resp = client.chat.completions.create(
        model=_model(),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "low"}},
                ],
            }
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    data = _extract_json(content)
    if not isinstance(data, dict):
        return {"description": str(data), "tags": []}
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "description": (data.get("description") or "").strip(),
        "tags": tags,
        "action_level": int(data.get("action_level") or 0) or None,
        "setting": (data.get("setting") or "").strip(),
        "has_vehicles": bool(data.get("has_vehicles")),
        "has_police": bool(data.get("has_police")),
        "has_explosion": bool(data.get("has_explosion")),
        "suitable_broll": bool(data.get("suitable_broll", True)),
    }


def analyze_highlight_moment(
    frame_paths: List[Path],
    *,
    time_sec: float,
    transcript_snip: str = "",
    audio_kind: str = "",
    video_title: str = "",
    video_context: str = "",
    streamer_name: str = "",
    frame_roles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Judge a candidate as a short-form clip.

    Industry pattern (Opus / Vizard / sports AV fusion): score setup → peak → reaction
    as a complete arc, not a single loud frame. Volume finds the peak; the reaction
    frame decides whether it's worth cutting.
    """
    if not frame_paths:
        return {
            "entertaining": False,
            "summary": "No frames",
            "score": 0,
            "title": "",
            "reason": "missing frames",
        }
    client = _client()
    roles = frame_roles or []
    if len(roles) < len(frame_paths):
        defaults = ["BEFORE (setup)", "PEAK (impact)", "AFTER (reaction)", "AFTER+ (aftermath)"]
        roles = list(roles) + defaults[len(roles):]
    context_line = (
        f"Title: {video_title or 'unknown'}. Creator: {streamer_name or 'unknown'}. "
        f"Context: {(video_context or '').strip() or 'infer from frames + transcript'}."
    )
    content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "You are a HARSH short-form clip scout (TikTok / Shorts / Reels).\n"
                "Frames are labeled BEFORE → PEAK → AFTER. Score the ARC, not one still.\n"
                "Industry rule: audio finds the peak; the AFTER reaction decides if it clips.\n\n"
                f"{context_line}\n"
                f"Peak ~{time_sec:.1f}s. Audio cue: {audio_kind or 'n/a'}.\n"
                f"Nearby transcript: {transcript_snip or 'n/a'}.\n\n"
                "Score FIVE axes 0–20 (sum ≈ virality when ×1, then we scale to 0–100):\n"
                "  hook — would the first 2s stop a scroll?\n"
                "  emotion — intensity / surprise / crowd energy\n"
                "  payoff — is there a clear finish / punchline / reveal?\n"
                "  standalone — stranger understands with zero prior context?\n"
                "  energy — visual + audio action (impacts, motion, roar)\n"
                "entertaining=true ONLY if payoff is real OR reaction is unmistakable.\n"
                "If audio includes climax_impact and AFTER shows knockdown / celebration / "
                "crash aftermath — score HIGH even with little speech.\n"
                "Spread scores honestly — most moments are mediocre. No defaulting to 70–85.\n"
                "Offsets: start before setup, end after reaction (usually 10–28s total).\n"
                "caption = quote or 3–6 word stake line. Never 'candidate moment'.\n"
                "Return JSON only:\n"
                '{"entertaining":true,"score":0-100,"virality_score":0-100,'
                '"hook_score":0-20,"emotion_score":0-20,"payoff_score":0-20,'
                '"standalone_score":0-20,"energy_score":0-20,'
                '"summary":"","hook":"","payoff":"","reaction":"",'
                '"title":"","caption":"","reason":"",'
                '"good_start_offset_sec":-6,"good_end_offset_sec":14,'
                '"needs_facecam":true}'
            ),
        }
    ]
    for i, path in enumerate(frame_paths[:4]):
        label = roles[i] if i < len(roles) else f"frame_{i}"
        content.append({"type": "text", "text": f"[{label}]"})
        content.append({
            "type": "image_url",
            "image_url": {"url": frame_to_data_url(path), "detail": "low"},
        })
    resp = client.chat.completions.create(
        model=_model(),
        messages=[{"role": "user", "content": content}],
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        data = _extract_json(raw)
    except Exception:
        return {
            "entertaining": False,
            "score": 0,
            "virality_score": 0,
            "summary": raw[:200],
            "hook": "",
            "payoff": "",
            "title": "",
            "caption": "",
            "reason": "parse_error",
            "good_start_offset_sec": -6,
            "good_end_offset_sec": 18,
            "needs_facecam": True,
        }
    if not isinstance(data, dict):
        return {"entertaining": False, "score": 0, "virality_score": 0, "summary": str(data), "title": ""}
    from app.studio.analysis.highlight_scoring import clean_caption_text, coerce_virality_score

    axes = {}
    for key in ("hook_score", "emotion_score", "payoff_score", "standalone_score", "energy_score"):
        try:
            axes[key] = max(0.0, min(20.0, float(data.get(key) or 0)))
        except (TypeError, ValueError):
            axes[key] = 0.0
    axis_sum = sum(axes.values())
    score = coerce_virality_score(data.get("virality_score"), data.get("score"))
    if axis_sum >= 25:
        # Prefer explicit dimensional scoring when the model filled it in
        score = max(score, min(100.0, axis_sum))
    snip = clean_caption_text(transcript_snip)
    caption = clean_caption_text(data.get("caption") or "") or snip[:120]
    title = clean_caption_text(data.get("title") or "")
    summary = clean_caption_text(data.get("summary") or "") or snip[:160]
    return {
        "entertaining": bool(data.get("entertaining")),
        "score": score,
        "virality_score": score,
        **axes,
        "summary": summary,
        "hook": (data.get("hook") or "").strip(),
        "payoff": (data.get("payoff") or "").strip(),
        "reaction": (data.get("reaction") or "").strip(),
        "title": title,
        "caption": caption,
        "reason": (data.get("reason") or "").strip(),
        "good_start_offset_sec": float(
            data.get("good_start_offset_sec") if data.get("good_start_offset_sec") is not None else -6
        ),
        "good_end_offset_sec": float(
            data.get("good_end_offset_sec") if data.get("good_end_offset_sec") is not None else 14
        ),
        "needs_facecam": bool(data.get("needs_facecam", True)),
    }
