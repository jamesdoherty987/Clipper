"""Rough cost estimates for GTA processing jobs."""
from __future__ import annotations

from typing import Any, Dict


# Approximate USD rates — illustrative budgeting, not invoices.
_RATES = {
    "whisper_per_min": 0.006,
    "gpt_input_per_1k": 0.005,
    "gpt_output_per_1k": 0.015,
    "vision_per_image": 0.004,
    "embedding_per_1k": 0.0001,
    "render_per_min": 0.02,
}


def estimate_explainer_cost(*, duration_sec: float = 45, vision_images: int = 0) -> Dict[str, Any]:
    mins = max(0.5, float(duration_sec or 45) / 60.0)
    total = (
        mins * _RATES["whisper_per_min"]
        + 2.0 * _RATES["gpt_input_per_1k"]
        + 1.0 * _RATES["gpt_output_per_1k"]
        + vision_images * _RATES["vision_per_image"]
        + mins * _RATES["render_per_min"]
    )
    return {
        "currency": "USD",
        "estimate": round(total, 3),
        "breakdown": {
            "transcription": round(mins * _RATES["whisper_per_min"], 3),
            "llm": round(2.0 * _RATES["gpt_input_per_1k"] + 1.0 * _RATES["gpt_output_per_1k"], 3),
            "vision": round(vision_images * _RATES["vision_per_image"], 3),
            "render": round(mins * _RATES["render_per_min"], 3),
        },
    }


def estimate_clip_job_cost(
    *,
    duration_sec: float,
    clip_count: int = 8,
    vision_candidates: int = 16,
) -> Dict[str, Any]:
    mins = max(1.0, float(duration_sec or 60) / 60.0)
    clips = max(1, int(clip_count or 8))
    visions = max(0, int(vision_candidates or 0))
    total = (
        mins * _RATES["whisper_per_min"]
        + visions * _RATES["vision_per_image"]
        + 4.0 * _RATES["gpt_input_per_1k"]
        + 2.0 * _RATES["gpt_output_per_1k"]
        + (clips * (float(duration_sec or 30) / max(clips, 1)) / 60.0) * _RATES["render_per_min"] * 0.4
    )
    return {
        "currency": "USD",
        "estimate": round(total, 3),
        "breakdown": {
            "transcription": round(mins * _RATES["whisper_per_min"], 3),
            "vision": round(visions * _RATES["vision_per_image"], 3),
            "llm": round(4.0 * _RATES["gpt_input_per_1k"] + 2.0 * _RATES["gpt_output_per_1k"], 3),
            "render": round(clips * 0.01, 3),
        },
    }


def estimate_library_ingest_cost(*, duration_sec: float, frame_count: int = 12) -> Dict[str, Any]:
    frames = max(1, int(frame_count or 12))
    total = frames * _RATES["vision_per_image"] + frames * 0.5 * _RATES["embedding_per_1k"]
    return {
        "currency": "USD",
        "estimate": round(total, 3),
        "breakdown": {
            "vision": round(frames * _RATES["vision_per_image"], 3),
            "embeddings": round(frames * 0.5 * _RATES["embedding_per_1k"], 3),
        },
    }
