"""Scene-change detection via FFmpeg (no PySceneDetect dependency)."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def detect_scene_changes(
    video_path: Path,
    *,
    threshold: float = 0.35,
    min_gap_sec: float = 2.0,
) -> List[Dict[str, Any]]:
    """Return timestamps where scene cuts are detected."""
    # showinfo prints pts_time for selected frames
    vf = f"select='gt(scene,{threshold})',showinfo"
    cmd = [
        "ffmpeg", "-hide_banner",
        "-i", str(video_path),
        "-vf", vf,
        "-fps_mode", "vfr",
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    times: List[float] = []
    for m in re.finditer(r"pts_time:([0-9.]+)", text):
        try:
            t = float(m.group(1))
        except ValueError:
            continue
        if times and (t - times[-1]) < min_gap_sec:
            continue
        times.append(t)
    return [{"time_sec": round(t, 2), "source": "scene", "score": 0.5} for t in times]


def sample_interval_times(duration_sec: float, every_sec: float = 12.0) -> List[float]:
    duration = max(0.0, float(duration_sec or 0))
    every = max(3.0, float(every_sec or 12))
    if duration <= 0:
        return [0.0]
    times = []
    t = every
    while t < duration - 1:
        times.append(round(t, 2))
        t += every
    if not times:
        times = [round(duration / 2, 2)]
    return times
