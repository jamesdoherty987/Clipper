"""OpenAI helpers for GTA topic research and script generation."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _model() -> str:
    return os.getenv("GTA_SCRIPT_MODEL") or os.getenv("CHAT_MODEL") or "gpt-4o"


def _client():
    from app.openai_client import get_openai_client

    return get_openai_client()


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty model response")
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
    raise ValueError("Could not parse JSON from model response")


_SYSTEM = (
    "You help create short-form GTA content ideas and scripts. "
    "Never present rumours, leaks, or speculation as confirmed facts. "
    "Clearly separate confirmed facts from speculation. "
    "Write for spoken short-form video (TikTok/Reels/Shorts), not articles. "
    "Return only valid JSON."
)


def generate_topics(count: int = 3, seed: str = "") -> List[Dict[str, Any]]:
    count = max(1, min(5, int(count or 3)))
    prompt = (
        f"Suggest {count} GTA short-form video topics suitable for 30–60 second explainers. "
        "Prefer evergreen preparation tips, confirmed official info framing, and clearly labelled speculation. "
        "Do not invent official announcements.\n"
    )
    if seed:
        prompt += f"User focus: {seed.strip()}\n"
    prompt += (
        'Return JSON: {"topics":[{"title":"","hook":"","summary":"",'
        '"source_links":[],"confirmed_facts":[],"speculation":[],'
        '"suggested_visuals":["police chase","city driving"]}]}'
    )
    client = _client()
    resp = client.chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    data = _extract_json(content)
    topics = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(topics, list):
        raise ValueError("Topic generation returned unexpected shape")
    out: List[Dict[str, Any]] = []
    for t in topics[:count]:
        if not isinstance(t, dict):
            continue
        out.append({
            "title": (t.get("title") or "GTA topic").strip(),
            "hook": (t.get("hook") or "").strip(),
            "summary": (t.get("summary") or "").strip(),
            "source_links": list(t.get("source_links") or []),
            "confirmed_facts": list(t.get("confirmed_facts") or []),
            "speculation": list(t.get("speculation") or []),
            "suggested_visuals": list(t.get("suggested_visuals") or []),
        })
    if not out:
        raise ValueError("No topics generated")
    return out


def generate_script(
    *,
    title: str = "",
    topic: str = "",
    hook: str = "",
    target_duration_sec: int = 45,
    notes: str = "",
) -> Dict[str, Any]:
    duration = max(20, min(90, int(target_duration_sec or 45)))
    prompt = (
        f"Write a short-form GTA explainer script (~{duration} seconds).\n"
        f"Title: {title or topic or 'GTA tip'}\n"
        f"Topic: {topic or title}\n"
        f"Preferred hook: {hook or '(invent a strong spoken hook)'}\n"
        f"Notes: {notes or 'none'}\n\n"
        "Structure: HOOK, 2–4 POINTS, ENDING CTA.\n"
        "Also include a visual_plan with gameplay search queries per section.\n"
        'Return JSON: {"title":"","target_duration_sec":45,"hook":"",'
        '"points":[{"label":"POINT 1","text":"","visuals":["police chase"]}],'
        '"ending":"","full_text":"","visual_plan":[{"section":"hook","query":"city driving"}]}'
    )
    client = _client()
    resp = client.chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    data = _extract_json(content)
    if not isinstance(data, dict):
        raise ValueError("Script generation returned unexpected shape")
    points = data.get("points") or []
    if not isinstance(points, list):
        points = []
    full_text = (data.get("full_text") or "").strip()
    if not full_text:
        parts = [(data.get("hook") or "").strip()]
        for p in points:
            if isinstance(p, dict):
                parts.append((p.get("text") or "").strip())
            else:
                parts.append(str(p).strip())
        parts.append((data.get("ending") or "").strip())
        full_text = "\n\n".join([p for p in parts if p])
    return {
        "title": (data.get("title") or title or topic or "GTA script").strip(),
        "target_duration_sec": int(data.get("target_duration_sec") or duration),
        "hook": (data.get("hook") or hook or "").strip(),
        "points": points,
        "ending": (data.get("ending") or "").strip(),
        "full_text": full_text,
        "visual_plan": list(data.get("visual_plan") or []),
    }
