"""Extract still frames from video at given timestamps."""
from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def extract_frame(
    video_path: Path,
    time_sec: float,
    output_path: Path,
    *,
    width: int = 768,
) -> Optional[Path]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{max(0.0, float(time_sec)):.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "3",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 100:
        logger.debug("[GTA] frame extract failed at %s: %s", time_sec, (proc.stderr or "")[-200:])
        return None
    return output_path


def extract_frames(
    video_path: Path,
    times: List[float],
    out_dir: Path,
    *,
    prefix: str = "frame",
    width: int = 768,
) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for i, t in enumerate(times):
        path = out_dir / f"{prefix}_{i:03d}_{int(t * 10)}.jpg"
        got = extract_frame(video_path, t, path, width=width)
        if got:
            paths.append(got)
    return paths


def frame_to_data_url(path: Path) -> str:
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
