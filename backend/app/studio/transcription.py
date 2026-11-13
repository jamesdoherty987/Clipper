"""Speech-to-text for facecam / streamer audio."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _client():
    from app.openai_client import get_openai_client

    return get_openai_client()


def transcribe_audio(path: Path) -> Dict[str, Any]:
    """Transcribe an audio/video file with OpenAI Whisper-compatible API.

    Returns {text, segments:[{start,end,text}]}.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Media file not found: {path}")
    model = os.getenv("GTA_TRANSCRIBE_MODEL") or "whisper-1"
    client = _client()
    with path.open("rb") as fh:
        # Prefer verbose_json for timestamps when supported.
        try:
            resp = client.audio.transcriptions.create(
                model=model,
                file=fh,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        except TypeError:
            fh.seek(0)
            resp = client.audio.transcriptions.create(
                model=model,
                file=fh,
                response_format="verbose_json",
            )
        except Exception:
            fh.seek(0)
            resp = client.audio.transcriptions.create(
                model=model,
                file=fh,
            )

    text = ""
    segments: List[Dict[str, Any]] = []
    if hasattr(resp, "text"):
        text = (resp.text or "").strip()
    elif isinstance(resp, dict):
        text = (resp.get("text") or "").strip()
    elif isinstance(resp, str):
        text = resp.strip()

    raw_segs = getattr(resp, "segments", None)
    if raw_segs is None and isinstance(resp, dict):
        raw_segs = resp.get("segments")
    if raw_segs:
        for s in raw_segs:
            if isinstance(s, dict):
                segments.append({
                    "start": float(s.get("start") or 0),
                    "end": float(s.get("end") or 0),
                    "text": (s.get("text") or "").strip(),
                })
            else:
                segments.append({
                    "start": float(getattr(s, "start", 0) or 0),
                    "end": float(getattr(s, "end", 0) or 0),
                    "text": (getattr(s, "text", "") or "").strip(),
                })

    if not segments and text:
        segments = [{"start": 0.0, "end": 0.0, "text": text}]

    return {"text": text, "segments": segments}
