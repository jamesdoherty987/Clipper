"""Caption / ASS subtitle generation with optional keyword highlighting."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set

_HIGHLIGHT_WORDS = {
    "gta", "police", "cops", "chase", "crash", "money", "heist", "mission",
    "secret", "easter", "launch", "online", "update", "feature", "warning",
    "never", "always", "first", "second", "third", "finally", "important",
}


def _ass_time(sec: float) -> str:
    sec = max(0.0, float(sec or 0))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _highlight_text(text: str, extra: Set[str] | None = None) -> str:
    words = re.findall(r"\S+|\s+", text)
    keys = set(_HIGHLIGHT_WORDS) | {k.lower() for k in (extra or set())}
    out = []
    for w in words:
        bare = re.sub(r"[^a-zA-Z0-9']", "", w).lower()
        if bare and bare in keys:
            out.append(r"{\c&H0000FFFF&}" + w + r"{\c&H00FFFFFF&}")
        else:
            out.append(w)
    return "".join(out)


def segments_to_ass(
    segments: List[Dict[str, Any]],
    output_path: Path,
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    highlight_keywords: bool = True,
    extra_keywords: List[str] | None = None,
) -> Path:
    """Write a centered ASS subtitle file from timed segments."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,68,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,1,5,0,2,48,48,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    cleaned = [s for s in (segments or []) if (s.get("text") or "").strip()]
    extra = set(extra_keywords or [])
    if not cleaned:
        output_path.write_text(header, encoding="utf-8")
        return output_path

    for i, seg in enumerate(cleaned):
        raw = (seg.get("text") or "").strip().replace("\n", " ")
        text = _highlight_text(raw, extra) if highlight_keywords else raw
        text = text.replace("\n", r"\N")
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or 0)
        if end <= start:
            end = start + max(1.5, min(4.0, len(raw.split()) * 0.35))
            if i + 1 < len(cleaned):
                nxt = float(cleaned[i + 1].get("start") or end)
                end = min(end, max(start + 0.8, nxt - 0.05))
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}\n"
        )
    output_path.write_text("".join(lines), encoding="utf-8")
    return output_path
