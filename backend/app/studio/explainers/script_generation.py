"""Topic research + script generation wrappers."""
from __future__ import annotations

from typing import Any, Dict, List

from app.studio import ai


def research_topics(store, *, count: int = 3, seed: str = "", created_by: str = "") -> List[Dict[str, Any]]:
    topics = ai.generate_topics(count=count, seed=seed)
    saved = []
    for t in topics:
        saved.append(store.create_gta_topic({**t, "created_by": created_by, "status": "suggested"}))
    return saved


def create_script_from_topic(
    store,
    *,
    topic_id: str = "",
    title: str = "",
    topic_text: str = "",
    hook: str = "",
    target_duration_sec: int = 45,
    notes: str = "",
    created_by: str = "",
) -> Dict[str, Any]:
    topic = store.get_gta_topic(topic_id) if topic_id else None
    generated = ai.generate_script(
        title=title or (topic or {}).get("title") or "",
        topic=topic_text or (topic or {}).get("summary") or (topic or {}).get("title") or "",
        hook=hook or (topic or {}).get("hook") or "",
        target_duration_sec=target_duration_sec,
        notes=notes,
    )
    return store.create_gta_script({
        **generated,
        "topic_id": topic_id or "",
        "created_by": created_by,
        "status": "draft",
    })
