"""Serial in-process job lanes for GTA Content Studio."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_KINDS = ("explainer_render", "library_ingest", "clip_job")

_LOCK = threading.Lock()
_RUNNING: dict[str, Optional[str]] = {
    "explainer_render": None,
    "library_ingest": None,
    "clip_job": None,
}


def _normalize_kind(kind: str) -> str:
    kind = (kind or "").strip().lower()
    if kind in ("explainer", "render", "explainer_render"):
        return "explainer_render"
    if kind in ("library", "ingest", "library_ingest"):
        return "library_ingest"
    if kind in ("clip", "clips", "clip_job", "streamer"):
        return "clip_job"
    if kind in _KINDS:
        return kind
    return "explainer_render"


def _start_fn(kind: str) -> Callable:
    if kind == "explainer_render":
        from app.studio.explainers.video_generation import start_explainer_job

        return start_explainer_job
    if kind == "library_ingest":
        from app.studio.gameplay_library.ingestion import start_library_ingest_job

        return start_library_ingest_job
    from app.studio.streamer_clips.pipeline import start_clip_job

    return start_clip_job


def enqueue_job(store, kind: str, job_id: str) -> dict:
    kind = _normalize_kind(kind)
    job = store.get_gta_job(job_id)
    if not job:
        return {}
    store.update_gta_job(job_id, {
        "status": "queued",
        "stage": "queued",
        "progress": "Queued — waiting to start…",
        "progress_percent": max(2, int(job.get("progress_percent") or 2)),
        "error": "",
    })
    with _LOCK:
        if _RUNNING.get(kind):
            return store.get_gta_job(job_id) or {}
        _RUNNING[kind] = job_id

    def _run():
        try:
            fn = _start_fn(kind)
            fn(store, job_id)
        except Exception as e:
            logger.exception("[GTA] job %s failed: %s", job_id, e)
            try:
                store.update_gta_job(job_id, {
                    "status": "failed",
                    "stage": "failed",
                    "progress": "Failed",
                    "error": str(e)[:800],
                })
            except Exception:
                pass
        finally:
            on_job_finished(store, kind, job_id)

    threading.Thread(target=_run, name=f"gta-{kind}-{job_id}", daemon=True).start()
    return store.get_gta_job(job_id) or {}


def on_job_finished(store, kind: str, job_id: str) -> None:
    kind = _normalize_kind(kind)
    next_id = None
    with _LOCK:
        if _RUNNING.get(kind) == job_id:
            _RUNNING[kind] = None
        # Pick next queued job of this type
        jobs = store.list_gta_studio().get("jobs") or []
        for j in sorted(jobs, key=lambda x: x.get("created_at") or ""):
            if j.get("type") != kind:
                continue
            if (j.get("status") or "") != "queued":
                continue
            if j.get("id") == job_id:
                continue
            next_id = j.get("id")
            _RUNNING[kind] = next_id
            break
    if next_id:
        def _run_next():
            try:
                fn = _start_fn(kind)
                fn(store, next_id)
            except Exception as e:
                logger.exception("[GTA] job %s failed: %s", next_id, e)
                try:
                    store.update_gta_job(next_id, {
                        "status": "failed",
                        "stage": "failed",
                        "progress": "Failed",
                        "error": str(e)[:800],
                    })
                except Exception:
                    pass
            finally:
                on_job_finished(store, kind, next_id)

        threading.Thread(target=_run_next, name=f"gta-{kind}-{next_id}", daemon=True).start()
