"""Render a single vertical streamer clip from a source window."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.studio.storage import upload_gta_path
from app.studio.video_engine.captions import segments_to_ass
from app.studio.video_engine.ffmpeg import (
    burn_subtitles,
    mix_music,
    overlay_logo,
    scale_crop_vertical,
    trim_clip,
    _run,
)
from app.studio.video_engine.ffmpeg import OUT_H, OUT_W

logger = logging.getLogger(__name__)


def _zoom_vertical(
    input_path: Path,
    output_path: Path,
    *,
    zoom_peak: float = 1.12,
) -> Path:
    """Subtle zoom punch for excitement — still 9:16 output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # zoompan can be heavy; use scale+crop with slight overscale as a stable alternative
    over_w = int(OUT_W * zoom_peak)
    over_h = int(OUT_H * zoom_peak)
    vf = (
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        return scale_crop_vertical(input_path, output_path)
    return output_path


def render_streamer_clip(
    source_path: Path,
    *,
    start_sec: float,
    end_sec: float,
    caption_segments: Optional[List[Dict[str, Any]]] = None,
    template: str = "fullscreen_gameplay",
    apply_zoom: bool = True,
    logo_path: Optional[Path] = None,
    music_path: Optional[Path] = None,
    music_volume: float = 0.1,
) -> Dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="gta_clip_"))
    try:
        cut = work / "cut.mp4"
        trim_clip(source_path, cut, start_sec, end_sec)

        vertical = work / "vertical.mp4"
        if apply_zoom:
            _zoom_vertical(cut, vertical)
        else:
            scale_crop_vertical(cut, vertical)

        current = vertical
        if caption_segments:
            # Shift caption times relative to clip start
            shifted = []
            for s in caption_segments:
                shifted.append({
                    "start": max(0.0, float(s.get("start") or 0) - float(start_sec)),
                    "end": max(0.0, float(s.get("end") or 0) - float(start_sec)),
                    "text": s.get("text") or "",
                })
            ass = work / "captions.ass"
            segments_to_ass(shifted, ass, highlight_keywords=True)
            captioned = work / "captioned.mp4"
            try:
                burn_subtitles(current, ass, captioned)
                current = captioned
            except Exception as e:
                logger.warning("[GTA] clip captions failed: %s", e)

        if logo_path and logo_path.exists():
            branded = work / "branded.mp4"
            overlay_logo(current, logo_path, branded)
            current = branded

        if music_path and music_path.exists():
            mixed = work / "mixed.mp4"
            mix_music(current, music_path, mixed, music_volume=music_volume)
            current = mixed

        final = work / "final.mp4"
        shutil.copyfile(current, final)
        url, filename = upload_gta_path(final, content_type="video/mp4", prefix="gta_clip")
        return {
            "url": url,
            "filename": filename,
            "duration_sec": max(0.1, float(end_sec) - float(start_sec)),
            "template": template or "fullscreen_gameplay",
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
