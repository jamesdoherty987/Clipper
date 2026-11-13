"""FFmpeg helpers for UGC Studio audio/video processing."""
from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    logger.info("[GTAClipper] ffmpeg: %s", " ".join(cmd[:8]) + ("..." if len(cmd) > 8 else ""))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def probe_media(path: Path) -> Dict[str, Any]:
    if not shutil.which("ffprobe"):
        return {}
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def media_summary(path: Path) -> Dict[str, Any]:
    data = probe_media(path)
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or 0) or None
    if duration is None and audio and audio.get("duration"):
        try:
            duration = float(audio.get("duration"))
        except (TypeError, ValueError):
            duration = None
    width = int(video.get("width") or 0) if video else None
    height = int(video.get("height") or 0) if video else None
    orientation = None
    if width and height:
        if height > width:
            orientation = "portrait"
        elif width > height:
            orientation = "landscape"
        else:
            orientation = "square"
    return {
        "duration_sec": round(duration, 3) if duration else None,
        "width": width,
        "height": height,
        "orientation": orientation,
        "resolution": f"{width}x{height}" if width and height else None,
        "has_audio": bool(audio),
        "has_video": bool(video),
        "size_bytes": int(fmt.get("size") or 0) or None,
    }


def audio_duration_sec(path: Path) -> Optional[float]:
    summary = media_summary(path)
    return summary.get("duration_sec")


def convert_to_wav(input_path: Path, output_path: Path, sample_rate: int = 44100) -> Path:
    """Convert any audio to mono PCM WAV (required by some Higgsfield speak paths)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Failed to convert audio to WAV: {proc.stderr[-800:]}")
    return output_path


def fit_audio_duration(
    input_path: Path,
    output_path: Path,
    target_sec: float,
    *,
    min_factor: float = 0.82,
    max_factor: float = 1.22,
    allow_slow: bool = False,
) -> Path:
    """Optionally speed audio up to fit a max length. Never slows speech by default.

    factor = current/target; factor>1 means speed up (shorter). Slowing (factor<1)
    is skipped unless allow_slow=True — stretched VO sounds unnatural and breaks lip sync.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    current = float(audio_duration_sec(input_path) or 0.0)
    target = max(0.8, float(target_sec))
    if current <= 0.05:
        shutil.copyfile(input_path, output_path)
        return output_path
    factor = current / target  # >1 means speed up (shorter)
    if factor < 1.0 and not allow_slow:
        shutil.copyfile(input_path, output_path)
        return output_path
    factor = max(min_factor, min(max_factor, factor))
    if abs(factor - 1.0) < 0.03:
        shutil.copyfile(input_path, output_path)
        return output_path
    # atempo only accepts 0.5–2.0; chain if needed
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-filter:a", ",".join(filters),
        "-vn",
        "-c:a", "libmp3lame",
        "-q:a", "4",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Failed to fit audio duration: {proc.stderr[-800:]}")
    return output_path


def pad_or_trim_audio(input_path: Path, output_path: Path, target_sec: float) -> Path:
    """Force audio to exactly target_sec — pad silence at the end or trim.

    Browser MediaRecorder WebM often has no duration header, so ffprobe can
    report 0 even when the file has real audio. Decode to WAV first before
    treating the input as empty silence.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target = max(0.5, float(target_sec))
    source = Path(input_path)
    current = float(audio_duration_sec(source) or 0.0)
    if current <= 0.05:
        # Re-probe after a proper decode — Chrome/Firefox WebM is the usual culprit.
        wav = output_path.parent / f"{output_path.stem}_probe.wav"
        try:
            convert_to_wav(source, wav)
            current = float(audio_duration_sec(wav) or 0.0)
            if current > 0.05 or (wav.exists() and wav.stat().st_size > 1024):
                source = wav
                if current <= 0.05:
                    # Decoded bytes exist but duration still missing — fit by force.
                    current = target
        except Exception:
            current = float(audio_duration_sec(source) or 0.0)

    if current <= 0.05:
        # Truly empty / unreadable — only then synthesize silence.
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=mono:sample_rate=44100",
            "-t", f"{target:.3f}",
            "-c:a", "libmp3lame",
            "-q:a", "4",
            str(output_path),
        ]
        proc = _run(cmd)
        if proc.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"Failed to create silent audio: {proc.stderr[-800:]}")
        return output_path
    if abs(current - target) < 0.04 and source.suffix.lower() in (".mp3", ".mpeg"):
        shutil.copyfile(source, output_path)
        return output_path
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-af", f"apad=whole_dur={target:.3f}",
        "-t", f"{target:.3f}",
        "-vn",
        "-c:a", "libmp3lame",
        "-q:a", "4",
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"Failed to pad/trim audio: {proc.stderr[-800:]}")
    return output_path


def extract_audio(video_path: Path, audio_out: Path, sample_rate: int = 44100) -> Path:
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        str(audio_out),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not audio_out.exists():
        raise RuntimeError(f"Failed to extract audio: {proc.stderr[-800:]}")
    return audio_out


# Consistent local voice disguises (no AI).
# Keep formants preserved so pitch shifts still sound like a real speaker —
# moving formants with pitch is what makes free disguise sound "manipulated".
VOICE_DISGUISE_PRESETS: Dict[str, Dict[str, Any]] = {
    "mask": {
        "label": "Mask",
        "blurb": "Default — natural, slightly different speaker (not deep)",
        # ~0.7 semitones down — soft identity shift, still sounds real
        "pitch": 0.96,
        "preserve_formant": True,
        "eq": (
            "equalizer=f=220:t=q:w=1.0:g=-0.6,"
            "equalizer=f=1400:t=q:w=1.1:g=0.8,"
            "equalizer=f=3200:t=q:w=1.1:g=-0.8,"
            "equalizer=f=5500:t=q:w=1.0:g=0.6,"
            "highpass=f=80,lowpass=f=14000"
        ),
    },
    "deeper": {
        "label": "Deeper",
        "blurb": "A bit lower — still natural, not a fake growl",
        # ~1.5 semitones down with preserved formants
        "pitch": 0.91,
        "preserve_formant": True,
        "eq": (
            "equalizer=f=180:t=q:w=1.0:g=1.0,"
            "equalizer=f=900:t=q:w=1.0:g=-0.8,"
            "equalizer=f=2500:t=q:w=1.1:g=-1.2,"
            "equalizer=f=5000:t=q:w=1.0:g=0.5,"
            "highpass=f=75,lowpass=f=13000"
        ),
    },
    "lighter": {
        "label": "Lighter",
        "blurb": "A bit brighter — still natural, not chipmunk",
        # ~1.2 semitones up with preserved formants
        "pitch": 1.07,
        "preserve_formant": True,
        "eq": (
            "equalizer=f=200:t=q:w=1.0:g=-1.0,"
            "equalizer=f=1500:t=q:w=1.1:g=1.0,"
            "equalizer=f=3400:t=q:w=1.1:g=1.2,"
            "equalizer=f=6000:t=q:w=1.0:g=0.8,"
            "highpass=f=90,lowpass=f=15000"
        ),
    },
}


