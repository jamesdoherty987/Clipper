"""Core FFmpeg helpers for GTA Content Studio."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ffmpeg_utils import ffmpeg_available, media_summary, probe_media

logger = logging.getLogger(__name__)

OUT_W = 1080
OUT_H = 1920


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    logger.info("[GTA] ffmpeg: %s", " ".join(cmd[:10]) + ("..." if len(cmd) > 10 else ""))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def trim_clip(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, float(start_sec or 0))
    end = max(start + 0.2, float(end_sec or start + 1))
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(input_path),
        "-t", f"{duration:.3f}",
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
        raise RuntimeError(f"trim failed: {proc.stderr[-800:]}")
    return output_path


def extract_audio_wav(video_path: Path, audio_out: Path) -> Path:
    from app.ffmpeg_utils import extract_audio

    return extract_audio(video_path, audio_out)


def normalize_audio(input_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        # Fallback: copy
        shutil.copyfile(input_path, output_path)
    return output_path


def scale_crop_vertical(input_path: Path, output_path: Path, width: int = OUT_W, height: int = OUT_H) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
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
        raise RuntimeError(f"vertical crop failed: {proc.stderr[-800:]}")
    return output_path


def burn_subtitles(input_path: Path, ass_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Escape path for ffmpeg subtitles filter
    ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", f"ass={ass}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"subtitle burn failed: {proc.stderr[-800:]}")
    return output_path


def mix_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    *,
    music_volume: float = 0.12,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vol = max(0.0, min(1.0, float(music_volume)))
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1",
        "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        shutil.copyfile(video_path, output_path)
    return output_path


def overlay_logo(
    video_path: Path,
    logo_path: Path,
    output_path: Path,
    *,
    width: int = 160,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(logo_path),
        "-filter_complex",
        f"[1:v]scale={width}:-1[lg];[0:v][lg]overlay=W-w-40:40",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        shutil.copyfile(video_path, output_path)
    return output_path


def concat_clips(paths: List[Path], output_path: Path) -> Path:
    """Concatenate clips with re-encode for consistent streams."""
    if not paths:
        raise ValueError("No clips to concatenate")
    if len(paths) == 1:
        shutil.copyfile(paths[0], output_path)
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.parent / "concat_list.txt"
    lines = []
    for p in paths:
        escaped = str(p).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
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
        raise RuntimeError(f"concat failed: {proc.stderr[-800:]}")
    return output_path


def media_info(path: Path) -> Dict[str, Any]:
    return media_summary(path)


__all__ = [
    "OUT_W",
    "OUT_H",
    "ffmpeg_available",
    "probe_media",
    "trim_clip",
    "extract_audio_wav",
    "normalize_audio",
    "scale_crop_vertical",
    "burn_subtitles",
    "mix_music",
    "overlay_logo",
    "concat_clips",
    "media_info",
    "_run",
]
