"""Vertical layout templates: facecam_top, fullscreen_gameplay, pip."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from app.studio.video_engine.ffmpeg import OUT_H, OUT_W, _run

logger = logging.getLogger(__name__)

TEMPLATES = ("facecam_top", "fullscreen_gameplay", "pip")


def compose_layout(
    *,
    facecam_path: Path,
    gameplay_path: Path,
    output_path: Path,
    template: str = "facecam_top",
    duration_sec: Optional[float] = None,
) -> Path:
    template = (template or "facecam_top").strip().lower()
    if template not in TEMPLATES:
        template = "facecam_top"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if template == "fullscreen_gameplay":
        return _fullscreen(gameplay_path, facecam_path, output_path, duration_sec)
    if template == "pip":
        return _pip(gameplay_path, facecam_path, output_path, duration_sec)
    return _facecam_top(facecam_path, gameplay_path, output_path, duration_sec)


def _dur_args(duration_sec: Optional[float]) -> list:
    if duration_sec and duration_sec > 0:
        return ["-t", f"{float(duration_sec):.3f}"]
    return []


def _facecam_top(
    facecam_path: Path,
    gameplay_path: Path,
    output_path: Path,
    duration_sec: Optional[float],
) -> Path:
    # Top 40% facecam, bottom 60% gameplay
    face_h = int(OUT_H * 0.4)
    game_h = OUT_H - face_h
    fc = (
        f"[0:v]scale={OUT_W}:{face_h}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{face_h},setsar=1[top];"
        f"[1:v]scale={OUT_W}:{game_h}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{game_h},setsar=1[bot];"
        f"[top][bot]vstack=inputs=2[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(facecam_path),
        "-stream_loop", "-1",
        "-i", str(gameplay_path),
        *_dur_args(duration_sec),
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"facecam_top layout failed: {proc.stderr[-900:]}")
    return output_path


def _fullscreen(
    gameplay_path: Path,
    facecam_path: Path,
    output_path: Path,
    duration_sec: Optional[float],
) -> Path:
    # Fullscreen gameplay with small facecam circle-ish rectangle bottom-right
    pip_w, pip_h = 320, 420
    fc = (
        f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},setsar=1[bg];"
        f"[1:v]scale={pip_w}:{pip_h}:force_original_aspect_ratio=increase,"
        f"crop={pip_w}:{pip_h},setsar=1[pip];"
        f"[bg][pip]overlay=W-w-36:H-h-220[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(gameplay_path),
        "-i", str(facecam_path),
        *_dur_args(duration_sec),
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "1:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"fullscreen layout failed: {proc.stderr[-900:]}")
    return output_path


def _pip(
    gameplay_path: Path,
    facecam_path: Path,
    output_path: Path,
    duration_sec: Optional[float],
) -> Path:
    pip_w, pip_h = 360, 480
    fc = (
        f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},setsar=1[bg];"
        f"[1:v]scale={pip_w}:{pip_h}:force_original_aspect_ratio=increase,"
        f"crop={pip_w}:{pip_h},setsar=1[pip];"
        f"[bg][pip]overlay=48:48[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(gameplay_path),
        "-i", str(facecam_path),
        *_dur_args(duration_sec),
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "1:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"pip layout failed: {proc.stderr[-900:]}")
    return output_path
