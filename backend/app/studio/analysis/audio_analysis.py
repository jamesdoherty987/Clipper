"""
Audio excitement, climax impacts, and silence cut-points.

Industry pattern (sports highlight papers + Opus/Vizard-style clippers):
- Continuous excitement curve beats isolated spikes
- Climax = sudden onset + loud peak + sustained aftermath (crowd / reaction)
- Pre-peak quiet contrast strengthens impact detection (build → hit)
- Silence / pause regions snap clean in/out points
"""
from __future__ import annotations

import logging
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _read_mono_pcm(wav_path: Path) -> Tuple[np.ndarray, int]:
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


def _load_samples(video_path: Path) -> Optional[Tuple[np.ndarray, int]]:
    work = video_path.parent
    wav = work / f"{video_path.stem}_audio_probe.wav"
    try:
        extract_pcm_wav(video_path, wav)
        return _read_mono_pcm(wav)
    except Exception as e:
        logger.warning("[GTA] audio extract failed: %s", e)
        return None
    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:
            pass


def _window_stats(samples: np.ndarray, rate: int, window_sec: float) -> List[Tuple[float, float, float, float]]:
    """Return list of (time, rms, peak, crest)."""
    win = max(1, int(rate * window_sec))
    n_windows = max(1, samples.size // win)
    out = []
    for i in range(n_windows):
        chunk = samples[i * win : (i + 1) * win]
        rms = float(np.sqrt(np.mean(chunk * chunk) + 1e-12))
        peak = float(np.max(np.abs(chunk)) + 1e-12)
        crest = peak / (rms + 1e-9)
        out.append((i * window_sec, rms, peak, crest))
    return out


def build_excitement_curve(
    samples: np.ndarray,
    rate: int,
    *,
    window_sec: float = 0.25,
) -> Dict[str, np.ndarray]:
    """
    Continuous multi-feature excitement timeline for THIS file.
    Returns arrays: times, rms, onset, sustain, excitement (0–1-ish).
    """
    stats = _window_stats(samples, rate, window_sec)
    if len(stats) < 8:
        empty = np.array([], dtype=np.float32)
        return {"times": empty, "rms": empty, "onset": empty, "sustain": empty, "excitement": empty}

    rms = np.array([s[1] for s in stats], dtype=np.float32)
    peak = np.array([s[2] for s in stats], dtype=np.float32)
    crest = np.array([s[3] for s in stats], dtype=np.float32)
    times = np.array([s[0] for s in stats], dtype=np.float32)

    lookback = max(3, int(2.0 / window_sec))
    onset = np.zeros_like(rms)
    for i in range(len(rms)):
        prev = rms[max(0, i - lookback):i]
        base = float(np.median(prev)) if prev.size else float(rms[i])
        onset[i] = max(0.0, float(rms[i] - base))

    lookahead = max(2, int(1.5 / window_sec))
    sustain = np.zeros_like(rms)
    for i in range(len(rms)):
        nxt = rms[i + 1 : i + 1 + lookahead]
        sustain[i] = float(np.mean(nxt)) if nxt.size else float(rms[i])

    # Pre-peak quiet: contrast vs quieter baseline ~0.8–1.5s before
    pre_quiet = np.zeros_like(rms)
    pre_n = max(2, int(1.0 / window_sec))
    for i in range(len(rms)):
        prev = rms[max(0, i - pre_n - 2): max(0, i - 1)]
        if prev.size:
            pre_quiet[i] = max(0.0, float(rms[i] - float(np.median(prev))))

    rms_p99 = float(np.percentile(rms, 99)) + 1e-9
    onset_p95 = float(np.percentile(onset, 95)) + 1e-9
    crest_p90 = float(np.percentile(crest, 90)) + 1e-9
    sustain_p95 = float(np.percentile(sustain, 95)) + 1e-9
    quiet_p95 = float(np.percentile(pre_quiet, 95)) + 1e-9

    excitement = (
        0.28 * np.clip(rms / rms_p99, 0, 2.5)
        + 0.28 * np.clip(onset / onset_p95, 0, 2.5)
        + 0.14 * np.clip(crest / crest_p90, 0, 2.0)
        + 0.18 * np.clip(sustain / sustain_p95, 0, 2.0)
        + 0.12 * np.clip(pre_quiet / quiet_p95, 0, 2.5)
    ).astype(np.float32)

    return {
        "times": times,
        "rms": rms,
        "peak": peak,
        "crest": crest,
        "onset": onset,
        "sustain": sustain,
        "pre_quiet": pre_quiet,
        "excitement": excitement,
        "window_sec": np.array([window_sec], dtype=np.float32),
    }


def detect_silence_regions(
    samples: np.ndarray,
    rate: int,
    *,
    window_sec: float = 0.2,
    min_silence_sec: float = 0.35,
) -> List[Dict[str, Any]]:
    """Find quiet gaps — natural cut points (MomentIQ / podcast clippers)."""
    stats = _window_stats(samples, rate, window_sec)
    if len(stats) < 5:
        return []
    rms = np.array([s[1] for s in stats], dtype=np.float32)
    times = np.array([s[0] for s in stats], dtype=np.float32)
    thr = float(np.percentile(rms, 18)) + 1e-6
    silent = rms < thr * 1.15

    regions: List[Dict[str, Any]] = []
    i = 0
    while i < len(silent):
        if not silent[i]:
            i += 1
            continue
        j = i
        while j < len(silent) and silent[j]:
            j += 1
        dur = (j - i) * window_sec
        if dur >= min_silence_sec:
            regions.append({
                "start_sec": round(float(times[i]), 2),
                "end_sec": round(float(times[min(j - 1, len(times) - 1)] + window_sec), 2),
                "duration_sec": round(dur, 2),
                "kind": "silence",
                "source": "silence",
            })
        i = j
    return regions


def detect_audio_spikes(
    video_path: Path,
    *,
    window_sec: float = 1.0,
    top_n: int = 40,
    min_separation_sec: float = 8.0,
    samples: Optional[np.ndarray] = None,
    rate: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return candidate moments ranked by loudness / energy variance."""
    if samples is None or rate is None:
        loaded = _load_samples(video_path)
        if not loaded:
            return []
        samples, rate = loaded

    if samples.size < rate:
        return []

    energies = []
    for t, rms, peak, _crest in _window_stats(samples, rate, window_sec):
        score = rms * 0.65 + (peak - rms) * 0.35
        energies.append((t, score, rms, peak))

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
            "weight": 1.25,
        })
        if len(picked) >= top_n:
            break
    return picked


def detect_energy_jumps(
    video_path: Path,
    *,
    window_sec: float = 0.5,
    top_n: int = 25,
    min_separation_sec: float = 7.0,
    samples: Optional[np.ndarray] = None,
    rate: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Sudden loudness jumps — laughs, impacts, reaction bursts."""
    if samples is None or rate is None:
        loaded = _load_samples(video_path)
        if not loaded:
            return []
        samples, rate = loaded

    if samples.size < rate * 2:
        return []

    stats = _window_stats(samples, rate, window_sec)
    rms_series = [s[1] for s in stats]
    jumps: List[Tuple[float, float, float]] = []
    for i in range(1, len(rms_series)):
        prev = rms_series[i - 1] + 1e-9
        cur = rms_series[i]
        delta = cur - prev
        ratio = cur / prev
        if delta < 0.035 and ratio < 1.45:
            continue
        score = delta * 0.7 + min(2.5, ratio - 1.0) * 0.3
        t = stats[i][0]
        jumps.append((t, score, cur))

    if not jumps:
        return []

    scores = np.array([j[1] for j in jumps], dtype=np.float32)
    mean = float(scores.mean())
    std = float(scores.std() + 1e-9)
    ranked = sorted(jumps, key=lambda x: x[1], reverse=True)
    picked: List[Dict[str, Any]] = []
    for t, score, rms in ranked:
        z = (score - mean) / std
        if z < 0.55 and len(picked) >= max(4, top_n // 3):
            continue
        if any(abs(t - p["time_sec"]) < min_separation_sec for p in picked):
            continue
        picked.append({
            "time_sec": round(float(t), 2),
            "score": round(float(min(1.6, 0.55 + z * 0.28)), 4),
            "z_score": round(float(z), 3),
            "rms": round(float(rms), 4),
            "kind": "energy_jump",
            "source": "audio_jump",
            "weight": 1.25,
        })
        if len(picked) >= top_n:
            break
    return picked


def detect_climax_impacts(
    video_path: Path,
    *,
    window_sec: float = 0.25,
    top_n: int = 12,
    min_separation_sec: float = 10.0,
    samples: Optional[np.ndarray] = None,
    rate: Optional[int] = None,
    curve: Optional[Dict[str, np.ndarray]] = None,
) -> List[Dict[str, Any]]:
    """
    Extreme audio climaxes — impact + roar pattern used in sports highlight systems.
    Ranked relative to THIS file only (genre-agnostic).
    """
    if curve is None:
        if samples is None or rate is None:
            loaded = _load_samples(video_path)
            if not loaded:
                return []
            samples, rate = loaded
        if samples.size < rate * 3:
            return []
        curve = build_excitement_curve(samples, rate, window_sec=window_sec)

    times = curve.get("times")
    excitement = curve.get("excitement")
    rms = curve.get("rms")
    peak = curve.get("peak")
    onset = curve.get("onset")
    sustain = curve.get("sustain")
    if times is None or excitement is None or len(times) < 8:
        return []

    mean = float(excitement.mean())
    std = float(excitement.std() + 1e-9)
    order = np.argsort(-excitement)

    def _pack(idx: int, *, global_max: bool = False) -> Dict[str, Any]:
        t = float(times[int(idx)])
        score = float(excitement[int(idx)])
        z = (score - mean) / std
        onset_v = float(onset[int(idx)]) if onset is not None else 0.0
        sustain_v = float(sustain[int(idx)]) if sustain is not None else 0.0
        rms_v = float(rms[int(idx)]) if rms is not None else 0.0
        strength = min(2.15, 0.95 + max(0.0, z) * 0.26)
        if sustain_v > rms_v * 0.85:
            strength = min(2.2, strength + 0.12)
        if global_max:
            strength = max(strength, 2.15)
            z = max(z, 2.5)
        return {
            "time_sec": round(t, 2),
            "score": round(strength, 4),
            "z_score": round(float(z), 3),
            "rms": round(rms_v, 4),
            "peak": round(float(peak[int(idx)]) if peak is not None else 0.0, 4),
            "excitement": round(score, 4),
            "kind": "climax_impact",
            "source": "audio_climax",
            "weight": 2.4 if global_max else 2.2,
            "climax": True,
            "global_max": global_max,
            "window_hint_pre_sec": 6.0,
            "window_hint_post_sec": 10.0,
        }

    # ALWAYS pin the absolute loudest excitement sample first (KO / goal / crash)
    picked: List[Dict[str, Any]] = []
    global_idx = int(np.argmax(excitement))
    picked.append(_pack(global_idx, global_max=True))

    onset_floor = float(np.percentile(onset, 60)) if onset is not None and len(onset) else 0.0
    for idx in order:
        if int(idx) == global_idx:
            continue
        t = float(times[int(idx)])
        score = float(excitement[int(idx)])
        z = (score - mean) / std
        if z < 1.2 and len(picked) >= max(2, top_n // 2):
            continue
        if z < 0.6:
            continue
        if any(abs(t - p["time_sec"]) < min_separation_sec for p in picked):
            continue
        onset_v = float(onset[int(idx)]) if onset is not None else 0.0
        # Soft filter — never block near-global outliers
        if onset_v < onset_floor and z < 1.6:
            continue
        picked.append(_pack(int(idx)))
        if len(picked) >= top_n:
            break
    return picked


def peaks_from_excitement_curve(
    curve: Dict[str, np.ndarray],
    *,
    top_n: int = 16,
    min_separation_sec: float = 9.0,
) -> List[Dict[str, Any]]:
    """Secondary candidates from the continuous excitement curve (not only climaxes)."""
    times = curve.get("times")
    excitement = curve.get("excitement")
    if times is None or excitement is None or len(times) < 8:
        return []
    mean = float(excitement.mean())
    std = float(excitement.std() + 1e-9)
    order = np.argsort(-excitement)
    picked: List[Dict[str, Any]] = []
    for idx in order:
        t = float(times[int(idx)])
        score = float(excitement[int(idx)])
        z = (score - mean) / std
        if z < 0.85 and len(picked) >= max(4, top_n // 2):
            continue
        if any(abs(t - p["time_sec"]) < min_separation_sec for p in picked):
            continue
        picked.append({
            "time_sec": round(t, 2),
            "score": round(min(1.55, 0.5 + z * 0.26), 4),
            "z_score": round(float(z), 3),
            "kind": "excitement_peak",
            "source": "audio_curve",
            "weight": 1.4,
        })
        if len(picked) >= top_n:
            break
    return picked


def analyze_audio_highlights(
    video_path: Path,
    *,
    spike_top_n: int = 40,
    jump_top_n: int = 25,
    climax_top_n: int = 12,
) -> Dict[str, Any]:
    """One PCM extract → spikes, jumps, climaxes, curve peaks, silences."""
    loaded = _load_samples(video_path)
    if not loaded:
        return {
            "spikes": [],
            "jumps": [],
            "climaxes": [],
            "curve_peaks": [],
            "silences": [],
        }
    samples, rate = loaded
    curve = build_excitement_curve(samples, rate, window_sec=0.25)
    return {
        "spikes": detect_audio_spikes(
            video_path, top_n=spike_top_n, samples=samples, rate=rate,
        ),
        "jumps": detect_energy_jumps(
            video_path, top_n=jump_top_n, samples=samples, rate=rate,
        ),
        "climaxes": detect_climax_impacts(
            video_path, top_n=climax_top_n, samples=samples, rate=rate, curve=curve,
        ),
        "curve_peaks": peaks_from_excitement_curve(curve, top_n=max(10, climax_top_n)),
        "silences": detect_silence_regions(samples, rate),
    }
