"""OpenAI embeddings stored on segments for semantic search (no pgvector required)."""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


def _model() -> str:
    return os.getenv("GTA_EMBED_MODEL") or "text-embedding-3-small"


def _client():
    from app.openai_client import get_openai_client

    return get_openai_client()


def embed_text(text: str) -> List[float]:
    text = (text or "").strip()
    if not text:
        return []
    client = _client()
    resp = client.embeddings.create(model=_model(), input=text[:8000])
    return list(resp.data[0].embedding)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def segment_embed_text(segment: Dict[str, Any]) -> str:
    return " ".join([
        segment.get("name") or "",
        segment.get("description") or "",
        " ".join(segment.get("tags") or []),
    ]).strip()


def ensure_segment_embedding(store, segment: Dict[str, Any]) -> Dict[str, Any]:
    if segment.get("embedding") and isinstance(segment.get("embedding"), list):
        return segment
    text = segment_embed_text(segment)
    if not text:
        return segment
    try:
        vec = embed_text(text)
    except Exception as e:
        logger.warning("[GTA] embedding failed: %s", e)
        return segment
    updated = store.update_gta_segment(segment["id"], {"embedding": vec})
    return updated or {**segment, "embedding": vec}
