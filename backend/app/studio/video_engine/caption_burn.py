"""Burn captions without libass/drawtext — render PNG overlays with Pillow."""
from __future__ import annotations

import logging
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.studio.video_engine.ffmpeg import OUT_FPS, OUT_H, OUT_W, _run, h264_args

logger = logging.getLogger(__name__)


def _load_font(size: int):
    from PIL import ImageFont

    size_i = max(8, int(round(float(size or 56))))
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size_i)
        except Exception:
            continue
    return ImageFont.load_default()


def _sizes(caption_size: str) -> int:
    return {"sm": 42, "md": 56, "lg": 70}.get((caption_size or "md").lower(), 56)


def _position_y(caption_position: str, box_h: int) -> int:
    pos = (caption_position or "bottom").lower()
    if pos == "top":
        return 180
    if pos == "center":
        return max(80, (OUT_H - box_h) // 2)
    return max(80, OUT_H - box_h - 220)


def _wrap(text: str, width: int = 18) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    return "\n".join(textwrap.wrap(text, width=width)[:3])


def render_caption_png(
    text: str,
    output_path: Path,
    *,
    caption_size: str = "md",
    caption_style: str = "viral",
    accent_color: Tuple[int, int, int] = (250, 204, 21),
) -> Path:
    from PIL import Image, ImageDraw

    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_size = _sizes(caption_size)
    if (caption_style or "").lower() == "lg" or caption_size == "lg":
        font_size = max(font_size, 64)
    font = _load_font(font_size)
    wrapped = _wrap(text, width=16 if caption_size == "lg" else 18)
    if not wrapped:
        # transparent 1x1
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(output_path)
        return output_path

    # Measure text
    dummy = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=8)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 28, 18
    box_w = min(OUT_W - 80, tw + pad_x * 2)
    box_h = th + pad_y * 2
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Soft dark plate for readability
    d.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=18, fill=(0, 0, 0, 150))
    x = (box_w - tw) / 2 - bbox[0]
    y = (box_h - th) / 2 - bbox[1]
    # Outline
    outline = (0, 0, 0, 255)
    for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2), (-2, 2), (2, -2)):
        d.multiline_text((x + ox, y + oy), wrapped, font=font, fill=outline, align="center", spacing=8)
    fill = (255, 255, 255, 255)
    if (caption_style or "").lower() == "viral":
        # slight accent glow on first line words handled as white + yellow underline bar
        d.multiline_text((x, y), wrapped, font=font, fill=fill, align="center", spacing=8)
        d.rectangle((box_w * 0.2, box_h - 8, box_w * 0.8, box_h - 4), fill=(*accent_color, 220))
    else:
        d.multiline_text((x, y), wrapped, font=font, fill=fill, align="center", spacing=8)
    img.save(output_path)
    return output_path


def burn_captions_with_overlay(
    video_path: Path,
    segments: List[Dict[str, Any]],
    output_path: Path,
    *,
    caption_style: str = "viral",
    caption_position: str = "bottom",
    caption_size: str = "md",
    accent_hex: str = "#FACC15",
    work_dir: Optional[Path] = None,
) -> Path:
    """
    Overlay timed caption PNGs onto video using ffmpeg overlay filters.
    Works even when ffmpeg was built without libass/freetype/drawtext.
    """
    cleaned = []
    for s in segments or []:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        start = max(0.0, float(s.get("start") or 0))
        end = max(start + 0.6, float(s.get("end") or start + 2.0))
        # Keep viral captions short
        words = text.split()
        if (caption_style or "").lower() == "viral" and len(words) > 8:
            text = " ".join(words[:8])
        cleaned.append({"start": start, "end": end, "text": text})

    if not cleaned:
        raise ValueError("No caption segments to burn")

    # Limit filter graph size
    cleaned = cleaned[:24]
    work = Path(work_dir or output_path.parent)
    work.mkdir(parents=True, exist_ok=True)

    accent = (250, 204, 21)
    h = (accent_hex or "").lstrip("#")
    if len(h) == 6:
        try:
            accent = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass

    pngs: List[Path] = []
    for i, seg in enumerate(cleaned):
        png = work / f"cap_{i:02d}.png"
        render_caption_png(
            seg["text"],
            png,
            caption_size=caption_size,
            caption_style=caption_style,
            accent_color=accent,
        )
        pngs.append(png)

    # Build filter: chain overlays with enable=between(t,start,end)
    inputs = ["-i", str(video_path)]
    for png in pngs:
        inputs.extend(["-i", str(png)])

    filters = [f"[0:v]fps={OUT_FPS}[base]"]
    last = "[base]"
    for i, seg in enumerate(cleaned):
        png_path = pngs[i]
        # Probe png size for positioning — default center-x
        try:
            from PIL import Image
            with Image.open(png_path) as im:
                box_h = im.size[1]
        except Exception:
            box_h = 120
        y = _position_y(caption_position, box_h)
        mid = f"[v{i}]"
        out = mid if i < len(cleaned) - 1 else "[vout]"
        # center horizontally; force CFR-friendly overlay
        filters.append(
            f"{last}[{i + 1}:v]overlay=(W-w)/2:{y}:enable='between(t,{seg['start']:.3f},{seg['end']:.3f})'{out}"
        )
        last = out
    filters.append("[vout]format=yuv420p[vfinal]")

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vfinal]",
        "-map", "0:a?",
        *h264_args(),
        str(output_path),
    ]
    proc = _run(cmd, timeout=1200)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"caption overlay failed: {(proc.stderr or '')[-900:]}")
    return output_path


def segments_from_fallback_text(
    text: str,
    *,
    duration_sec: float,
) -> List[Dict[str, Any]]:
    """Split a transcript snip into timed caption chunks covering the clip."""
    words = re.findall(r"\S+", (text or "").strip())
    if not words:
        return []
    duration_sec = max(2.0, float(duration_sec or 8))
    # ~4 words per card
    chunks = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)]
    chunks = chunks[:8]
    slot = duration_sec / max(1, len(chunks))
    out = []
    t = 0.15
    for c in chunks:
        start = t
        end = min(duration_sec - 0.1, t + max(1.2, slot * 0.9))
        out.append({"start": round(start, 2), "end": round(end, 2), "text": c})
        t = end + 0.05
    return out
