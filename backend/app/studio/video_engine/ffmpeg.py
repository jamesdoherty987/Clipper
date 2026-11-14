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
OUT_FPS = 30


def h264_args(*, audio: bool = True, crf: int = 23) -> list[str]:
    """Web-friendly H.264 encode — constant 30fps, yuv420p, faststart."""
    args = [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(int(crf)),
        "-profile:v", "main",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        "-r", str(OUT_FPS),
        "-fps_mode", "cfr",
        "-g", str(OUT_FPS * 2),
        "-movflags", "+faststart",
    ]
    if audio:
        args.extend(["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"])
    return args


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
        "-vf", f"fps={OUT_FPS},format=yuv420p",
        *h264_args(),
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
        f"fps={OUT_FPS},"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        *h264_args(),
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
    position: str = "top_right",
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pos = (position or "top_right").lower()
    overlay = {
        "top_left": "40:40",
        "top_right": "W-w-40:40",
        "bottom_left": "40:H-h-40",
        "bottom_right": "W-w-40:H-h-40",
    }.get(pos, "W-w-40:40")
    w = max(80, min(280, int(width or 160)))
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(logo_path),
        "-filter_complex",
        f"[0:v]fps={OUT_FPS}[base];[1:v]scale={w}:-1[lg];[base][lg]overlay={overlay},format=yuv420p[v]",
        "-map", "[v]",
        "-map", "0:a?",
        *h264_args(),
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        shutil.copyfile(video_path, output_path)
    return output_path


def _ffmpeg_drawtext_escape(text: str) -> str:
    text = (text or "").replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    text = text.replace("%", "%%").replace("\n", " ")
    return text[:90]


def make_intro_card(
    output_path: Path,
    *,
    title: str,
    subtitle: str = "",
    duration_sec: float = 1.6,
) -> Path:
    """Solid 9:16 intro card with title + optional subtitle."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(0.8, min(4.0, float(duration_sec or 1.6)))
    title_e = _ffmpeg_drawtext_escape(title or "Clip")
    sub_e = _ffmpeg_drawtext_escape(subtitle or "")
    draw = (
        f"drawtext=text='{title_e}':fontcolor=white:fontsize=64:font=Arial:"
        f"x=(w-text_w)/2:y=(h/2)-70:box=1:boxcolor=0x00000088:boxborderw=18"
    )
    if sub_e:
        draw += (
            f",drawtext=text='{sub_e}':fontcolor=0xbbf7d0:fontsize=36:font=Arial:"
            f"x=(w-text_w)/2:y=(h/2)+30"
        )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x0b1220:s={OUT_W}x{OUT_H}:d={dur:.2f}:r={OUT_FPS}",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo:d={dur:.2f}",
        "-vf", draw,
        *h264_args(),
        "-shortest",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        # Fallback: plain color card without text
        cmd2 = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x0b1220:s={OUT_W}x{OUT_H}:d={dur:.2f}:r={OUT_FPS}",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo:d={dur:.2f}",
            *h264_args(),
            "-shortest",
            str(output_path),
        ]
        proc2 = _run(cmd2)
        if proc2.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"intro card failed: {(proc.stderr or '')[-800:]}")
    return output_path


def compose_reaction_stack(
    input_path: Path,
    output_path: Path,
    *,
    split_ratio: float = 0.42,
    cam_anchor: str = "top_right",
) -> Path:
    """
    Same-source split: reaction zoom on top, gameplay crop on bottom.
    Works from a single streamer VOD without a separate facecam file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ratio = max(0.28, min(0.55, float(split_ratio or 0.42)))
    face_h = int(OUT_H * ratio)
    game_h = OUT_H - face_h
    anchor = (cam_anchor or "top_right").lower()
    # Crop window inside source frame for the reaction pane
    crop = {
        "top_left": "iw*0.32:ih*0.48:iw*0.02:ih*0.02",
        "top_right": "iw*0.32:ih*0.48:iw*0.66:ih*0.02",
        "top_center": "iw*0.34:ih*0.48:(iw-ow)/2:ih*0.02",
        "center": "iw*0.36:ih*0.42:(iw-ow)/2:(ih-oh)/2",
    }.get(anchor, "iw*0.32:ih*0.48:iw*0.66:ih*0.02")
    fc = (
        f"[0:v]fps={OUT_FPS},split=2[cam][game];"
        f"[cam]crop={crop},"
        f"scale={OUT_W}:{face_h}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{face_h},setsar=1[top];"
        f"[game]scale={OUT_W}:{game_h}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{game_h},setsar=1[bot];"
        f"[top][bot]vstack=inputs=2,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "0:a?",
        *h264_args(),
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        logger.warning("[GTA] reaction_stack failed, falling back to vertical: %s", (proc.stderr or "")[-400:])
        return scale_crop_vertical(input_path, output_path)
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
        "-vf", f"fps={OUT_FPS},format=yuv420p",
        *h264_args(),
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
    "OUT_FPS",
    "h264_args",
    "ffmpeg_available",
    "probe_media",
    "trim_clip",
    "extract_audio_wav",
    "normalize_audio",
    "scale_crop_vertical",
    "burn_subtitles",
    "mix_music",
    "overlay_logo",
    "make_intro_card",
    "compose_reaction_stack",
    "concat_clips",
    "media_info",
    "_run",
]
