"""Detect excitement spikes from audio energy (no librosa dependency)."""
from __future__ import annotations

import logging
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def extract_pcm_wav(video_path: Path, wav_path: Path, sample_rate: int = 16000) -> Path:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not wav_path.exists():
        raise RuntimeError(f"audio extract failed: {(proc.stderr or '')[-600:]}")
    return wav_path


def _read_mono_pcm(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        width = wf.getsampwidth()
        channels = wf.getnchannels()
    if width != 2:
        raise ValueError("expected 16-bit PCM")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples /= 32768.0
    return samples, rate


def detect_audio_spikes(
    video_path: Path,
    *,
    window_sec: float = 1.0,
    top_n: int = 40,
    min_separation_sec: float = 8.0,
) -> List[Dict[str, Any]]:
    """Return candidate moments ranked by loudness / energy variance."""
    work = video_path.parent
    wav = work / f"{video_path.stem}_energy.wav"
    try:
        extract_pcm_wav(video_path, wav)
        samples, rate = _read_mono_pcm(wav)
    except Exception as e:
        logger.warning("[GTA] audio spike analysis failed: %s", e)
        return []
    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:
            pass

    if samples.size < rate:
        return []

    win = max(1, int(rate * window_sec))
    n_windows = max(1, samples.size // win)
    energies = []
    for i in range(n_windows):
        chunk = samples[i * win : (i + 1) * win]
        rms = float(np.sqrt(np.mean(chunk * chunk) + 1e-12))
        # Crest-ish: peak vs rms suggests shouts / impacts
        peak = float(np.max(np.abs(chunk)) + 1e-12)
        score = rms * 0.65 + (peak - rms) * 0.35
        energies.append((i * window_sec, score, rms, peak))

    if not energies:
        return []

    scores = np.array([e[1] for e in energies], dtype=np.float32)
    mean = float(scores.mean())
    std = float(scores.std() + 1e-9)
    ranked = sorted(energies, key=lambda x: x[1], reverse=True)

    picked: List[Dict[str, Any]] = []
    for t, score, rms, peak in ranked:
        if score < mean + 0.35 * std and len(picked) >= max(5, top_n // 3):
            continue
        if any(abs(t - p["time_sec"]) < min_separation_sec for p in picked):
            continue
        z = (score - mean) / std
        kind = "shout" if peak > 0.55 and z > 1.2 else "excitement" if z > 0.8 else "energy"
        picked.append({
            "time_sec": round(float(t), 2),
            "score": round(float(score), 4),
            "z_score": round(float(z), 3),
            "rms": round(float(rms), 4),
            "peak": round(float(peak), 4),
            "kind": kind,
            "source": "audio",
        })
        if len(picked) >= top_n:
            break
    return picked
