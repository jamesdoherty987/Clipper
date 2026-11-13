"""Transcribe facecam and softly align to script sections."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from app.studio.transcription import transcribe_audio

logger = logging.getLogger(__name__)


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _overlap_score(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, len(sa | sb))


def script_sections(script: Dict[str, Any]) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []
    hook = (script.get("hook") or "").strip()
    if hook:
        sections.append({"id": "hook", "label": "HOOK", "text": hook})
    for i, p in enumerate(script.get("points") or []):
        if isinstance(p, dict):
            text = (p.get("text") or "").strip()
            label = (p.get("label") or f"POINT {i + 1}").strip()
        else:
            text = str(p).strip()
            label = f"POINT {i + 1}"
        if text:
            sections.append({"id": f"point_{i + 1}", "label": label, "text": text})
    ending = (script.get("ending") or "").strip()
    if ending:
        sections.append({"id": "ending", "label": "ENDING", "text": ending})
    if not sections and (script.get("full_text") or "").strip():
        sections.append({"id": "body", "label": "BODY", "text": script["full_text"].strip()})
    return sections


def align_transcript_to_script(
    script: Dict[str, Any],
    transcript_segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Tolerant alignment: map script sections onto transcript time ranges."""
    sections = script_sections(script)
    segs = [s for s in (transcript_segments or []) if (s.get("text") or "").strip()]
    if not sections:
        return {"sections": [], "tolerance": "empty_script"}
    if not segs:
        # Even distribution fallback using target duration
        total = float(script.get("target_duration_sec") or 45)
        slot = total / len(sections)
        aligned = []
        for i, sec in enumerate(sections):
            aligned.append({
                **sec,
                "start": round(i * slot, 3),
                "end": round((i + 1) * slot, 3),
                "match_score": 0.0,
                "matched_text": "",
            })
        return {"sections": aligned, "tolerance": "no_transcript"}

    # Greedy window match across consecutive transcript segments
    aligned = []
    cursor = 0
    for si, sec in enumerate(sections):
        target_toks = _tokens(sec["text"])
        best_score = -1.0
        best_range = (cursor, min(len(segs), cursor + 1))
        remaining_sections = max(1, len(sections) - si)
        max_end = len(segs) - remaining_sections + 1
        for start_i in range(cursor, max(cursor + 1, max_end + 1)):
            acc: List[str] = []
            for end_i in range(start_i + 1, len(segs) + 1):
                acc.extend(_tokens(segs[end_i - 1].get("text") or ""))
                score = _overlap_score(target_toks, acc)
                if score > best_score:
                    best_score = score
                    best_range = (start_i, end_i)
                # Stop growing window if already long enough vs script words
                if len(acc) > max(8, int(len(target_toks) * 1.8)):
                    break
            if start_i > cursor + 3 and best_score > 0.15:
                break
        s_i, e_i = best_range
        start_t = float(segs[s_i].get("start") or 0)
        end_t = float(segs[e_i - 1].get("end") or start_t)
        if end_t <= start_t:
            end_t = start_t + 2.0
        matched = " ".join((segs[j].get("text") or "").strip() for j in range(s_i, e_i)).strip()
        aligned.append({
            **sec,
            "start": round(start_t, 3),
            "end": round(end_t, 3),
            "match_score": round(max(0.0, best_score), 3),
            "matched_text": matched,
        })
        cursor = max(cursor + 1, e_i)

    return {"sections": aligned, "tolerance": "fuzzy"}


def analyze_recording(facecam_path: Path, script: Dict[str, Any]) -> Dict[str, Any]:
    transcript = transcribe_audio(facecam_path)
    alignment = align_transcript_to_script(script, transcript.get("segments") or [])
    return {
        "transcript": transcript.get("text") or "",
        "transcript_segments": transcript.get("segments") or [],
        "alignment": alignment,
    }
