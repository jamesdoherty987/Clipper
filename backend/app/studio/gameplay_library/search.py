"""Keyword + semantic search over gameplay segments."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from app.studio.gameplay_library.embeddings import cosine, embed_text

logger = logging.getLogger(__name__)


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def search_segments(store, query: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    segments = store.list_gta_studio().get("segments") or []
    if not q:
        return segments[:limit]

    q_tokens = set(_tokens(q))
    query_vec = None
    try:
        query_vec = embed_text(q)
    except Exception as e:
        logger.warning("[GTA] semantic search embed failed: %s", e)

    ranked = []
    for seg in segments:
        blob = " ".join([
            seg.get("name") or "",
            seg.get("description") or "",
            " ".join(seg.get("tags") or []),
        ])
        s_tokens = set(_tokens(blob))
        keyword = len(q_tokens & s_tokens) / max(1, len(q_tokens)) if q_tokens else 0.0
        semantic = 0.0
        emb = seg.get("embedding")
        if query_vec and isinstance(emb, list) and emb:
            semantic = cosine(query_vec, emb)
        score = max(keyword, 0.0) * 0.45 + max(semantic, 0.0) * 0.55
        if score <= 0 and keyword <= 0 and semantic <= 0:
            # Still allow weak substring matches
            if q.lower() in blob.lower():
                score = 0.15
        ranked.append((score, seg))

    ranked.sort(key=lambda x: x[0], reverse=True)
    positive = [seg for score, seg in ranked if score > 0.05]
    return (positive or [seg for _, seg in ranked])[:limit]
