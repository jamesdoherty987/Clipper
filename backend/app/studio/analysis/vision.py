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
) -> Dict[str, Any]:
    """Judge whether a candidate moment is entertaining for a short clip."""
    if not frame_paths:
        return {
            "entertaining": False,
            "summary": "No frames",
            "score": 0,
            "title": "",
            "reason": "missing frames",
        }
    client = _client()
    content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "You are scoring a potential short-form GTA streamer clip moment. "
                f"Timestamp ~{time_sec:.1f}s. Audio cue: {audio_kind or 'n/a'}. "
                f"Nearby transcript: {transcript_snip or 'n/a'}.\n"
                "Score how good this would be as a 20–45s Short/Reels clip. "
                "Prefer funny reactions, crashes, chases, surprise, clear action. "
                "Return JSON only: "
                '{"entertaining":true,"score":0-100,"summary":"",'
                '"title":"","caption":"","reason":"",'
                '"good_start_offset_sec":-4,"good_end_offset_sec":12,'
                '"needs_facecam":true}'
            ),
        }
    ]
    for path in frame_paths[:3]:
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
            "summary": raw[:200],
            "title": "",
            "caption": "",
            "reason": "parse_error",
            "good_start_offset_sec": -5,
            "good_end_offset_sec": 12,
            "needs_facecam": True,
        }
    if not isinstance(data, dict):
        return {"entertaining": False, "score": 0, "summary": str(data), "title": ""}
    return {
        "entertaining": bool(data.get("entertaining")),
        "score": float(data.get("score") or 0),
        "summary": (data.get("summary") or "").strip(),
        "title": (data.get("title") or "").strip(),
        "caption": (data.get("caption") or "").strip(),
        "reason": (data.get("reason") or "").strip(),
        "good_start_offset_sec": float(data.get("good_start_offset_sec") if data.get("good_start_offset_sec") is not None else -5),
        "good_end_offset_sec": float(data.get("good_end_offset_sec") if data.get("good_end_offset_sec") is not None else 12),
        "needs_facecam": bool(data.get("needs_facecam", True)),
    }
