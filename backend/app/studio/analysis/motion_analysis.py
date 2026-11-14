"""Optical-motion intensity via low-res frame diffs (sports/gaming action cue)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _sample_gray_frames(
    video_path: Path,
    *,
    fps: float = 2.0,
    width: int = 160,
) -> Tuple[Optional[np.ndarray], float]:
    """
    Decode a tiny grayscale stream for motion scoring.
    Returns (frames [N,H,W] float32 0-1, sample_interval_sec) or (None, 0).
    """
    out = video_path.parent / f"{video_path.stem}_motion_probe.raw"
    h = max(90, int(round(width * 9 / 16)))
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps={fps},scale={width}:{h},format=gray",
        "-f", "rawvideo",
        str(out),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not out.exists() or out.stat().st_size < width * h:
            logger.warning("[GTA] motion extract failed: %s", (proc.stderr or "")[-300:])
            return None, 0.0
        raw = np.fromfile(str(out), dtype=np.uint8)
        n = raw.size // (width * h)
        if n < 4:
            return None, 0.0
        frames = raw[: n * width * h].reshape(n, h, width).astype(np.float32) / 255.0
        return frames, 1.0 / max(0.25, float(fps))
    except Exception as e:
        logger.warning("[GTA] motion analysis failed: %s", e)
        return None, 0.0
    finally:
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass


def detect_motion_peaks(
    video_path: Path,
    *,
    top_n: int = 20,
    min_separation_sec: float = 8.0,
    fps: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Rank sudden visual action bursts (punches landing, crashes, camera whip).
    Genre-agnostic: scores relative to THIS file's motion distribution.
    """
    frames, dt = _sample_gray_frames(video_path, fps=fps)
    if frames is None or dt <= 0:
        return []

    diffs = np.mean(np.abs(frames[1:] - frames[:-1]), axis=(1, 2))
    if diffs.size < 3:
        return []

    # Smooth a touch so single-frame noise doesn't dominate
    kernel = np.array([0.2, 0.6, 0.2], dtype=np.float32)
    padded = np.pad(diffs, (1, 1), mode="edge")
    smooth = np.convolve(padded, kernel, mode="valid")[: diffs.size]

    mean = float(smooth.mean())
    std = float(smooth.std() + 1e-9)
    # Onset of motion relative to local baseline
    lookback = max(2, int(1.5 / dt))
    onset = np.zeros_like(smooth)
    for i in range(len(smooth)):
        base = float(np.median(smooth[max(0, i - lookback):i])) if i else float(smooth[i])
        onset[i] = max(0.0, float(smooth[i] - base))

    scores = 0.55 * ((smooth - mean) / std) + 0.45 * (onset / (float(np.percentile(onset, 95)) + 1e-9))
    order = np.argsort(-scores)

    picked: List[Dict[str, Any]] = []
    for idx in order:
        t = float((int(idx) + 1) * dt)  # diff belongs to the later frame
        z = float(scores[int(idx)])
        if z < 0.9 and len(picked) >= max(3, top_n // 2):
            continue
        if any(abs(t - p["time_sec"]) < min_separation_sec for p in picked):
            continue
        strength = min(1.7, 0.55 + max(0.0, z) * 0.28)
        picked.append({
            "time_sec": round(t, 2),
            "score": round(strength, 4),
            "z_score": round(z, 3),
            "motion": round(float(smooth[int(idx)]), 5),
            "kind": "motion_burst",
            "source": "motion",
            "weight": 1.35,
        })
        if len(picked) >= top_n:
            break
    return picked
