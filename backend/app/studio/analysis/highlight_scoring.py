"""Merge candidates and rank final clip windows with GPT."""
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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return json.loads(m.group(1).strip())
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("could not parse ranking JSON")


def merge_candidates(
    *,
    audio: List[Dict[str, Any]],
    scenes: List[Dict[str, Any]],
    transcript_peaks: List[Dict[str, Any]],
    duration_sec: float,
    max_candidates: int = 24,
) -> List[Dict[str, Any]]:
    """Cluster nearby signals into candidate highlight centers."""
    raw = []
    for a in audio or []:
        raw.append({**a, "weight": 1.2})
    for s in scenes or []:
        raw.append({**s, "weight": 0.55})
    for t in transcript_peaks or []:
        raw.append({**t, "weight": 1.0})

    raw = [c for c in raw if 0 <= float(c.get("time_sec") or 0) <= max(0.0, duration_sec - 1)]
    raw.sort(key=lambda x: float(x.get("time_sec") or 0))

    clusters: List[Dict[str, Any]] = []
    for c in raw:
        t = float(c.get("time_sec") or 0)
        if clusters and abs(t - clusters[-1]["time_sec"]) < 6.0:
            prev = clusters[-1]
            w = float(c.get("weight") or 1)
            prev["score"] = float(prev.get("score") or 0) + float(c.get("score") or 0.4) * w
            prev["sources"].append(c.get("source") or "mixed")
            prev["kinds"].append(c.get("kind") or c.get("source") or "")
            # Pull center toward stronger signal
            prev["time_sec"] = round((prev["time_sec"] + t) / 2, 2)
        else:
            clusters.append({
                "time_sec": round(t, 2),
                "score": float(c.get("score") or 0.4) * float(c.get("weight") or 1),
                "sources": [c.get("source") or "mixed"],
                "kinds": [c.get("kind") or c.get("source") or ""],
            })

    clusters.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return clusters[:max_candidates]


def transcript_reaction_peaks(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Heuristic: laughter / swearing / hype words in transcript."""
    keys = re.compile(
        r"\b(lol|lmao|omg|what|holy|no way|bro|dude|insane|crazy|oh my|wtf|haha|laugh|"
        r"crash|police|cops|chase|explode|explosion|died|dead)\b",
        re.I,
    )
    out = []
    for s in segments or []:
        text = s.get("text") or ""
        if not keys.search(text):
            continue
        start = float(s.get("start") or 0)
        out.append({
            "time_sec": round(start, 2),
            "score": 0.8,
            "kind": "reaction_line",
            "source": "transcript",
            "text": text.strip()[:160],
        })
    return out


def gpt_rank_clips(
    candidates: List[Dict[str, Any]],
    *,
    streamer_name: str = "",
    target_count: int = 8,
    target_duration_sec: int = 30,
) -> List[Dict[str, Any]]:
    """Ask GPT to pick/rank the best final clip windows."""
    if not candidates:
        return []
    compact = []
    for c in candidates[:20]:
        compact.append({
            "time_sec": c.get("time_sec"),
            "vision_score": c.get("vision_score"),
            "summary": c.get("summary") or c.get("vision_summary") or "",
            "title": c.get("title") or "",
            "audio_kinds": c.get("kinds") or [],
            "entertaining": c.get("entertaining"),
            "start_sec": c.get("start_sec"),
            "end_sec": c.get("end_sec"),
        })
    prompt = (
        f"Rank streamer highlight clips for short-form GTA content. "
        f"Streamer: {streamer_name or 'unknown'}. Want ~{target_count} clips "
        f"around {target_duration_sec}s each.\n"
        "Prefer moments that work standalone, have a clear event + reaction, "
        "and a clean beginning/ending. Avoid near-duplicates.\n"
        f"Candidates:\n{json.dumps(compact, ensure_ascii=False)}\n"
        "Return JSON: {\"clips\":[{\"time_sec\":0,\"start_sec\":0,\"end_sec\":30,"
        "\"score\":0-100,\"title\":\"\",\"caption\":\"\",\"reason\":\"\"}]}"
    )
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": "You rank short-form gaming clips. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        data = _extract_json(resp.choices[0].message.content or "")
        clips = data.get("clips") if isinstance(data, dict) else data
        if not isinstance(clips, list):
            raise ValueError("bad shape")
        out = []
        for c in clips[:target_count]:
            if not isinstance(c, dict):
                continue
            out.append({
                "time_sec": float(c.get("time_sec") or 0),
                "start_sec": float(c.get("start_sec") or 0),
                "end_sec": float(c.get("end_sec") or 0),
                "score": float(c.get("score") or 0),
                "title": (c.get("title") or "").strip(),
                "caption": (c.get("caption") or "").strip(),
                "reason": (c.get("reason") or "").strip(),
            })
        if out:
            return out
    except Exception as e:
        logger.warning("[GTA] gpt rank failed, using heuristic: %s", e)

    # Fallback: use vision-scored candidates
    ranked = sorted(candidates, key=lambda x: float(x.get("vision_score") or x.get("score") or 0), reverse=True)
    out = []
    for c in ranked[:target_count]:
        start = float(c.get("start_sec") if c.get("start_sec") is not None else max(0, float(c.get("time_sec") or 0) - 5))
        end = float(c.get("end_sec") if c.get("end_sec") is not None else start + target_duration_sec)
        out.append({
            "time_sec": float(c.get("time_sec") or start),
            "start_sec": start,
            "end_sec": end,
            "score": float(c.get("vision_score") or c.get("score") or 0),
            "title": (c.get("title") or "Highlight").strip(),
            "caption": (c.get("caption") or c.get("summary") or "").strip(),
            "reason": (c.get("reason") or "").strip(),
        })
    return out
