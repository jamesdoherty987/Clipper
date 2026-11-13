"""Branding / graphic overlay helpers (Milestone A: logo passthrough)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.studio.video_engine.ffmpeg import overlay_logo


def apply_branding(
    video_path: Path,
    output_path: Path,
    *,
    logo_path: Optional[Path] = None,
) -> Path:
    if logo_path and logo_path.exists():
        return overlay_logo(video_path, logo_path, output_path)
    if video_path != output_path:
        output_path.write_bytes(video_path.read_bytes())
    return output_path
