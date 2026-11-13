"""Match script sections to tagged gameplay library segments."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.studio.gameplay_library.embeddings import cosine, embed_text

logger = logging.getLogger(__name__)


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def score_segment(query: str, segment: Dict[str, Any], query_vec: Optional[List[float]] = None) -> float:
    q = set(_tokens(query))
    blob = " ".join([
        segment.get("name") or "",
        segment.get("description") or "",
        " ".join(segment.get("tags") or []),
    ])
    s = set(_tokens(blob))
    keyword = (len(q & s) / max(1, len(q))) if q else 0.0
    semantic = 0.0
    emb = segment.get("embedding")
    if query_vec and isinstance(emb, list) and emb:
        semantic = cosine(query_vec, emb)
    return max(keyword, 0.0) * 0.4 + max(semantic, 0.0) * 0.6


def select_gameplay_for_sections(
    store,
    sections: List[Dict[str, Any]],
    visual_plan: Optional[List[Dict[str, Any]]] = None,
    *,
    require_commercial: bool = True,
) -> List[Dict[str, Any]]:
    segments = store.list_gta_studio().get("segments") or []
    annotated = []
    for seg in segments:
        source_id = (seg.get("source_id") or "").strip()
        source = store.get_gta_source(source_id) if source_id else None
        ok = bool(
            source
            and source.get("permission_status") == "approved"
            and source.get("commercial_use")
        )
        row = dict(seg)
        row["_commercial_ok"] = ok
        annotated.append(row)
    if require_commercial:
        segments = [s for s in annotated if s.get("_commercial_ok")]
    else:
        segments = annotated

    plan_by_section = {}
    for item in visual_plan or []:
        if isinstance(item, dict):
            key = (item.get("section") or "").strip().lower()
            if key:
                plan_by_section[key] = (item.get("query") or item.get("visuals") or "")

    used_ids = set()
    selections: List[Dict[str, Any]] = []
    for sec in sections or []:
        sec_id = (sec.get("id") or "").strip().lower()
        query_parts = [sec.get("text") or "", sec.get("label") or ""]
        plan = plan_by_section.get(sec_id) or plan_by_section.get((sec.get("label") or "").lower())
        if isinstance(plan, list):
            query_parts.extend([str(x) for x in plan])
        elif plan:
            query_parts.append(str(plan))
        query = " ".join(query_parts)
        query_vec = None
        try:
            if query.strip():
                query_vec = embed_text(query)
        except Exception as e:
            logger.debug("[GTA] section embed failed: %s", e)

        ranked = []
        for seg in segments:
            if seg.get("id") in used_ids:
                continue
            ranked.append((score_segment(query, seg, query_vec=query_vec), seg))
        ranked.sort(key=lambda x: x[0], reverse=True)

        chosen = ranked[0][1] if ranked else None
        score = ranked[0][0] if ranked else 0.0
        # If score is weak, still pick first unused segment so render can proceed
        if (not chosen or score < 0.05) and segments:
            for seg in segments:
                if seg.get("id") not in used_ids:
                    chosen = seg
                    score = score_segment(query, seg, query_vec=query_vec)
                    break

        if chosen:
            used_ids.add(chosen.get("id"))
            selections.append({
                "section_id": sec.get("id"),
                "section_label": sec.get("label"),
                "section_start": sec.get("start"),
                "section_end": sec.get("end"),
                "segment_id": chosen.get("id"),
                "video_id": chosen.get("video_id"),
                "url": chosen.get("url"),
                "start_sec": chosen.get("start_sec"),
                "end_sec": chosen.get("end_sec"),
                "tags": chosen.get("tags") or [],
                "description": chosen.get("description") or "",
                "match_score": round(float(score), 3),
                "commercial_ok": bool(chosen.get("_commercial_ok", True)),
                "source_id": chosen.get("source_id") or "",
            })
        else:
            selections.append({
                "section_id": sec.get("id"),
                "section_label": sec.get("label"),
                "section_start": sec.get("start"),
                "section_end": sec.get("end"),
                "segment_id": "",
                "error": "No gameplay segments in library",
                "match_score": 0.0,
                "commercial_ok": False,
            })
    return selections
