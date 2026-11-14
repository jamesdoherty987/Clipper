"""Caption / ASS subtitle generation with styles and keyword highlighting."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set

_HIGHLIGHT_WORDS = {
    "gta", "police", "cops", "chase", "crash", "money", "heist", "mission",
    "secret", "easter", "launch", "online", "update", "feature", "warning",
    "never", "always", "first", "second", "third", "finally", "important",
    "bro", "dude", "insane", "crazy", "wtf", "omg", "no", "way",
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


def _ass_color(hex_color: str, alpha: str = "00") -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR&."""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}&".upper()


def _highlight_text(text: str, extra: Set[str] | None = None, accent: str = "#FACC15") -> str:
    words = re.findall(r"\S+|\s+", text)
    keys = set(_HIGHLIGHT_WORDS) | {k.lower() for k in (extra or set())}
    accent_ass = _ass_color(accent)
    out = []
    for w in words:
        bare = re.sub(r"[^a-zA-Z0-9']", "", w).lower()
        if bare and bare in keys:
            out.append(r"{\c" + accent_ass + "}" + w + r"{\c&H00FFFFFF&}")
        else:
            out.append(w)
    return "".join(out)


def _style_params(
    *,
    caption_style: str = "viral",
    caption_position: str = "bottom",
    caption_size: str = "md",
) -> Dict[str, Any]:
    sizes = {"sm": 52, "md": 68, "lg": 84}
    fontsize = sizes.get((caption_size or "md").lower(), 68)
    # ASS alignment: 8 top-center, 5 middle-center, 2 bottom-center
    align = {"top": 8, "center": 5, "bottom": 2}.get((caption_position or "bottom").lower(), 2)
    margin_v = {"top": 220, "center": 40, "bottom": 240}.get((caption_position or "bottom").lower(), 240)
    style = (caption_style or "viral").lower()
    if style == "clean":
        outline, shadow, bold = 3, 0, 0
        font = "Arial"
    elif style == "bold":
        outline, shadow, bold = 6, 1, -1
        font = "Arial Black"
        fontsize = int(fontsize * 1.05)
    else:  # viral
        outline, shadow, bold = 7, 0, -1
        font = "Arial Black"
        fontsize = int(fontsize * 1.08)
    return {
        "fontsize": fontsize,
        "align": align,
        "margin_v": margin_v,
        "outline": outline,
        "shadow": shadow,
        "bold": bold,
        "font": font,
    }


def segments_to_ass(
    segments: List[Dict[str, Any]],
    output_path: Path,
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    highlight_keywords: bool = True,
    extra_keywords: List[str] | None = None,
    caption_style: str = "viral",
    caption_position: str = "bottom",
    caption_size: str = "md",
    accent_color: str = "#FACC15",
) -> Path:
    """Write a styled ASS subtitle file from timed segments."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    p = _style_params(
        caption_style=caption_style,
        caption_position=caption_position,
        caption_size=caption_size,
    )
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{p['font']},{p['fontsize']},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,{p['bold']},0,0,0,100,100,0,0,1,{p['outline']},{p['shadow']},{p['align']},48,48,{p['margin_v']},1

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
        # Keep captions punchy for viral style
        words = raw.split()
        if (caption_style or "").lower() == "viral" and len(words) > 8:
            raw = " ".join(words[:8])
        text = _highlight_text(raw, extra, accent_color) if highlight_keywords else raw
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
