"""JSON-file store for GTAClipper (replaces BookedForYou AdminOpsStore)."""
from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()

ROOT = Path(os.getenv("GTACLIPPER_DATA") or Path(__file__).resolve().parents[2] / "data")
STORE_PATH = Path(os.getenv("GTACLIPPER_STORE") or ROOT / "store.json")

_DEFAULT: Dict[str, Any] = {
    "gta_videos": [],
    "gta_jobs": [],
    "gta_topics": [],
    "gta_scripts": [],
    "gta_recordings": [],
    "gta_exports": [],
    "gta_clips": [],
    "gta_gameplay_segments": [],
    "gta_sources": [],
    "gta_settings": {},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _norm_list(data: Dict[str, Any], key: str) -> None:
    if not isinstance(data.get(key), list):
        data[key] = []


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or STORE_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(copy.deepcopy(_DEFAULT))

    def _read(self) -> Dict[str, Any]:
        with _LOCK:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            data = copy.deepcopy(_DEFAULT)
            data.update(raw or {})
            for k in _DEFAULT:
                if k != "gta_settings":
                    _norm_list(data, k)
            if not isinstance(data.get("gta_settings"), dict):
                data["gta_settings"] = {}
            return data

    def _write(self, data: Dict[str, Any]) -> None:
        with _LOCK:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def mutate(self, fn) -> Dict[str, Any]:
        with _LOCK:
            data = self._read()
            fn(data)
            self._write(data)
            return data

    def load(self) -> Dict[str, Any]:
        return self._read()

    def list_gta_studio(self) -> Dict[str, Any]:
        data = self._read()
        def sort_key(x):
            return x.get("updated_at") or x.get("created_at") or ""
        return {
            "videos": sorted(data["gta_videos"], key=sort_key, reverse=True),
            "jobs": sorted(data["gta_jobs"], key=sort_key, reverse=True),
            "topics": sorted(data["gta_topics"], key=sort_key, reverse=True),
            "scripts": sorted(data["gta_scripts"], key=sort_key, reverse=True),
            "recordings": sorted(data["gta_recordings"], key=sort_key, reverse=True),
            "exports": sorted(data["gta_exports"], key=sort_key, reverse=True),
            "clips": sorted(data["gta_clips"], key=sort_key, reverse=True),
            "segments": sorted(data["gta_gameplay_segments"], key=sort_key, reverse=True),
            "sources": sorted(data["gta_sources"], key=sort_key, reverse=True),
            "settings": self.get_gta_settings(),
        }

    def get_gta_overview(self) -> Dict[str, Any]:
        studio = self.list_gta_studio()
        exports = studio["exports"]
        return {
            "videos_created": len(exports),
            "awaiting_review": len([e for e in exports if e.get("status") == "needs_review"]),
            "completed": len([e for e in exports if e.get("status") == "approved"]),
            "recent_jobs": studio["jobs"][:12],
            "recent_exports": exports[:12],
            "topics": studio["topics"][:6],
            "settings": studio["settings"],
        }

    def get_gta_settings(self) -> Dict[str, Any]:
        raw = dict(self._read().get("gta_settings") or {})
        raw.setdefault("default_template", "facecam_top")
        raw.setdefault("logo_url", "")
        raw.setdefault("music_url", "")
        raw.setdefault("music_volume", 0.12)
        raw.setdefault("email_finished_videos", False)
        raw.setdefault("notify_email", "")
        raw.setdefault("channel_name", "GTAClipper")
        raw.setdefault("brand_color", "#22c55e")
        return raw

    def update_gta_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        def _upd(data):
            cur = dict(data.get("gta_settings") or {})
            for k, v in (payload or {}).items():
                cur[k] = v
            data["gta_settings"] = cur
        self.mutate(_upd)
        return self.get_gta_settings()

    def _created_by(self, payload: Dict[str, Any]) -> str:
        return (payload.get("created_by") or "local").strip() or "local"

    def _get(self, key: str, item_id: str) -> Optional[Dict[str, Any]]:
        for item in self._read().get(key) or []:
            if item.get("id") == item_id:
                return dict(item)
        return None

    def _update(self, key: str, item_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updated = None
        def _upd(data):
            nonlocal updated
            for item in data.get(key) or []:
                if item.get("id") != item_id:
                    continue
                for k, v in payload.items():
                    item[k] = v
                item["updated_at"] = _now()
                updated = dict(item)
                break
        self.mutate(_upd)
        return updated

    def create_gta_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        platforms = payload.get("platforms_allowed") or []
        if isinstance(platforms, str):
            platforms = [p.strip() for p in platforms.split(",") if p.strip()]
        item = {
            "id": _id("gtasrc"),
            "name": (payload.get("name") or "Source").strip(),
            "provider": (payload.get("provider") or "").strip(),
            "permission_status": (payload.get("permission_status") or "pending").strip().lower(),
            "commercial_use": bool(payload.get("commercial_use")),
            "platforms_allowed": platforms,
            "expiry": (payload.get("expiry") or "").strip(),
            "attribution_required": bool(payload.get("attribution_required")),
            "notes": (payload.get("notes") or "").strip(),
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_sources", []).append(item))
        return item

    def get_gta_source(self, source_id: str):
        return self._get("gta_sources", source_id)

    def update_gta_source(self, source_id: str, payload: Dict[str, Any]):
        return self._update("gta_sources", source_id, payload)

    def assert_gta_source_commercial_ok(self, source_id: str) -> Dict[str, Any]:
        if not source_id:
            raise ValueError("A rights source is required for commercial export")
        source = self.get_gta_source(source_id)
        if not source:
            raise ValueError("Footage source not found")
        if source.get("permission_status") != "approved":
            raise ValueError("Commercial publishing blocked: permission status is not approved")
        if not source.get("commercial_use"):
            raise ValueError("Commercial publishing blocked: not marked for commercial use")
        return source

    def create_gta_video(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = (payload.get("url") or "").strip()
        if not url:
            raise ValueError("Video URL is required")
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        item = {
            "id": _id("gtavid"),
            "name": (payload.get("name") or "Video").strip(),
            "kind": (payload.get("kind") or "gameplay").strip(),
            "url": url,
            "content_type": (payload.get("content_type") or "video/mp4").strip(),
            "size_bytes": int(payload.get("size_bytes") or 0),
            "duration_sec": payload.get("duration_sec"),
            "source_id": (payload.get("source_id") or "").strip(),
            "streamer_name": (payload.get("streamer_name") or "").strip(),
            "tags": tags,
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_videos", []).append(item))
        return item

    def get_gta_video(self, video_id: str):
        return self._get("gta_videos", video_id)

    def create_gta_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        job_type = (payload.get("type") or "explainer_render").strip()
        item = {
            "id": _id("gtajob"),
            "name": (payload.get("name") or job_type).strip(),
            "type": job_type,
            "status": "queued",
            "stage": "queued",
            "progress": "Queued",
            "progress_percent": 2,
            "error": "",
            "cost_estimate": payload.get("cost_estimate"),
            "payload": dict(payload.get("payload") or {}),
            "result": {},
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
            "completed_at": "",
        }
        self.mutate(lambda d: d.setdefault("gta_jobs", []).append(item))
        return item

    def get_gta_job(self, job_id: str):
        return self._get("gta_jobs", job_id)

    def update_gta_job(self, job_id: str, payload: Dict[str, Any]):
        return self._update("gta_jobs", job_id, payload)

    def create_gta_topic(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = {
            "id": _id("gtatopic"),
            "title": (payload.get("title") or "Untitled").strip(),
            "hook": (payload.get("hook") or "").strip(),
            "summary": (payload.get("summary") or "").strip(),
            "source_links": list(payload.get("source_links") or []),
            "confirmed_facts": list(payload.get("confirmed_facts") or []),
            "speculation": list(payload.get("speculation") or []),
            "suggested_visuals": list(payload.get("suggested_visuals") or []),
            "status": (payload.get("status") or "suggested").strip(),
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_topics", []).append(item))
        return item

    def get_gta_topic(self, topic_id: str):
        return self._get("gta_topics", topic_id)

    def create_gta_script(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        points = payload.get("points") or []
        full_text = (payload.get("full_text") or "").strip()
        if not full_text:
            parts = [(payload.get("hook") or "").strip()]
            for p in points:
                parts.append((p.get("text") if isinstance(p, dict) else str(p)).strip())
            parts.append((payload.get("ending") or "").strip())
            full_text = "\n\n".join([p for p in parts if p])
        item = {
            "id": _id("gtascript"),
            "topic_id": (payload.get("topic_id") or "").strip(),
            "title": (payload.get("title") or "Untitled script").strip(),
            "target_duration_sec": int(payload.get("target_duration_sec") or 45),
            "hook": (payload.get("hook") or "").strip(),
            "points": points if isinstance(points, list) else [],
            "ending": (payload.get("ending") or "").strip(),
            "full_text": full_text,
            "visual_plan": list(payload.get("visual_plan") or []),
            "captions": list(payload.get("captions") or []),
            "status": (payload.get("status") or "draft").strip(),
            "version": int(payload.get("version") or 1),
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_scripts", []).append(item))
        return item

    def get_gta_script(self, script_id: str):
        return self._get("gta_scripts", script_id)

    def update_gta_script(self, script_id: str, payload: Dict[str, Any]):
        return self._update("gta_scripts", script_id, payload)

    def create_gta_recording(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = (payload.get("url") or "").strip()
        if not url:
            raise ValueError("Recording URL is required")
        item = {
            "id": _id("gtarec"),
            "script_id": (payload.get("script_id") or "").strip(),
            "name": (payload.get("name") or "Facecam").strip(),
            "url": url,
            "content_type": (payload.get("content_type") or "video/mp4").strip(),
            "size_bytes": int(payload.get("size_bytes") or 0),
            "duration_sec": payload.get("duration_sec"),
            "transcript": (payload.get("transcript") or "").strip(),
            "transcript_segments": list(payload.get("transcript_segments") or []),
            "alignment": dict(payload.get("alignment") or {}),
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_recordings", []).append(item))
        return item

    def get_gta_recording(self, recording_id: str):
        return self._get("gta_recordings", recording_id)

    def update_gta_recording(self, recording_id: str, payload: Dict[str, Any]):
        return self._update("gta_recordings", recording_id, payload)

    def create_gta_export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = {
            "id": _id("gtaexp"),
            "name": (payload.get("name") or "Export").strip(),
            "pipeline": (payload.get("pipeline") or "explainer").strip(),
            "job_id": (payload.get("job_id") or "").strip(),
            "clip_id": (payload.get("clip_id") or "").strip(),
            "script_id": (payload.get("script_id") or "").strip(),
            "recording_id": (payload.get("recording_id") or "").strip(),
            "url": (payload.get("url") or "").strip(),
            "thumbnail_url": (payload.get("thumbnail_url") or "").strip(),
            "duration_sec": payload.get("duration_sec"),
            "template": (payload.get("template") or "facecam_top").strip(),
            "status": (payload.get("status") or "needs_review").strip(),
            "title": (payload.get("title") or "").strip(),
            "caption": (payload.get("caption") or "").strip(),
            "score": payload.get("score"),
            "source_timestamp": (payload.get("source_timestamp") or "").strip(),
            "gameplay_selection": list(payload.get("gameplay_selection") or []),
            "cost_estimate": payload.get("cost_estimate"),
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_exports", []).append(item))
        return item

    def get_gta_export(self, export_id: str):
        return self._get("gta_exports", export_id)

    def update_gta_export(self, export_id: str, payload: Dict[str, Any]):
        return self._update("gta_exports", export_id, payload)

    def set_export_status(self, export_id: str, status: str):
        """Approve/reject an export and keep the linked streamer clip in sync."""
        export = self.update_gta_export(export_id, {"status": status})
        if not export:
            return None
        clip_status = {"approved": "approved", "rejected": "rejected"}.get(status)
        if not clip_status:
            return export
        clip_id = (export.get("clip_id") or "").strip()
        if clip_id:
            self.update_gta_clip(clip_id, {"status": clip_status})
            return export
        url = (export.get("url") or "").strip()
        job_id = (export.get("job_id") or "").strip()
        if not url and not job_id:
            return export

        def _sync(data: Dict[str, Any]):
            for clip in data.get("gta_clips") or []:
                if clip_id and clip.get("id") == clip_id:
                    clip["status"] = clip_status
                    clip["updated_at"] = _now()
                elif url and clip.get("url") == url:
                    clip["status"] = clip_status
                    clip["updated_at"] = _now()
                elif job_id and clip.get("job_id") == job_id and clip.get("title") == export.get("title"):
                    clip["status"] = clip_status
                    clip["updated_at"] = _now()

        self.mutate(_sync)
        return export

    def set_clip_status(self, clip_id: str, status: str):
        """Approve/reject a clip and keep matching review exports in sync."""
        clip = self.update_gta_clip(clip_id, {"status": status})
        if not clip:
            return None
        export_status = {"approved": "approved", "rejected": "rejected", "pending": "needs_review"}.get(
            status, "needs_review"
        )
        url = (clip.get("url") or "").strip()
        job_id = (clip.get("job_id") or "").strip()

        def _sync(data: Dict[str, Any]):
            for exp in data.get("gta_exports") or []:
                if exp.get("clip_id") == clip_id:
                    exp["status"] = export_status
                    exp["updated_at"] = _now()
                elif url and exp.get("url") == url:
                    exp["status"] = export_status
                    exp["updated_at"] = _now()
                elif job_id and exp.get("job_id") == job_id and exp.get("title") == clip.get("title"):
                    exp["status"] = export_status
                    exp["updated_at"] = _now()

        self.mutate(_sync)
        return clip

    def create_gta_clip(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = {
            "id": _id("gtaclip"),
            "job_id": (payload.get("job_id") or "").strip(),
            "video_id": (payload.get("video_id") or "").strip(),
            "title": (payload.get("title") or "").strip(),
            "caption": (payload.get("caption") or "").strip(),
            "url": (payload.get("url") or "").strip(),
            "thumbnail_url": (payload.get("thumbnail_url") or "").strip(),
            "duration_sec": payload.get("duration_sec"),
            "score": payload.get("score"),
            "source_start_sec": payload.get("source_start_sec"),
            "source_end_sec": payload.get("source_end_sec"),
            "template": (payload.get("template") or "fullscreen_gameplay").strip(),
            "reason": (payload.get("reason") or "").strip(),
            "transcript_snip": (payload.get("transcript_snip") or "").strip(),
            "status": (payload.get("status") or "pending").strip(),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_clips", []).append(item))
        return item

    def update_gta_clip(self, clip_id: str, payload: Dict[str, Any]):
        return self._update("gta_clips", clip_id, payload)

    def _collect_media_urls(self, *items: Dict[str, Any]) -> List[str]:
        urls: List[str] = []
        for item in items:
            if not item:
                continue
            for key in ("url", "thumbnail_url"):
                u = (item.get(key) or "").strip()
                if u:
                    urls.append(u)
        return urls

    def delete_gta_export(self, export_id: str, *, delete_files: bool = True) -> Optional[Dict[str, Any]]:
        export = self.get_gta_export(export_id)
        if not export:
            return None
        removed = {"export": None, "clip": None, "deleted_files": 0}

        def _del(data: Dict[str, Any]):
            exports = data.get("gta_exports") or []
            data["gta_exports"] = [e for e in exports if e.get("id") != export_id]
            removed["export"] = export
            clip_id = (export.get("clip_id") or "").strip()
            if clip_id:
                clips = data.get("gta_clips") or []
                kept = []
                for c in clips:
                    if c.get("id") == clip_id:
                        removed["clip"] = dict(c)
                    else:
                        kept.append(c)
                data["gta_clips"] = kept

        self.mutate(_del)
        if delete_files:
            from app.r2_compat import delete_media_url
            for url in self._collect_media_urls(removed.get("export") or {}, removed.get("clip") or {}):
                if delete_media_url(url):
                    removed["deleted_files"] += 1
        return removed

    def delete_gta_clip(self, clip_id: str, *, delete_files: bool = True) -> Optional[Dict[str, Any]]:
        clip = None
        for c in self.list_gta_studio().get("clips") or []:
            if c.get("id") == clip_id:
                clip = c
                break
        if not clip:
            return None
        removed = {"clip": clip, "exports": [], "deleted_files": 0}

        def _del(data: Dict[str, Any]):
            data["gta_clips"] = [c for c in (data.get("gta_clips") or []) if c.get("id") != clip_id]
            kept_exports = []
            for e in data.get("gta_exports") or []:
                if e.get("clip_id") == clip_id or (
                    e.get("job_id") == clip.get("job_id")
                    and e.get("url")
                    and e.get("url") == clip.get("url")
                ):
                    removed["exports"].append(dict(e))
                else:
                    kept_exports.append(e)
            data["gta_exports"] = kept_exports

        self.mutate(_del)
        if delete_files:
            from app.r2_compat import delete_media_url
            urls = self._collect_media_urls(clip, *removed["exports"])
            for url in urls:
                if delete_media_url(url):
                    removed["deleted_files"] += 1
        return removed

    def delete_gta_job(self, job_id: str, *, delete_files: bool = True) -> Optional[Dict[str, Any]]:
        """Delete a run and all clips/exports produced by it."""
        job = self.get_gta_job(job_id)
        if not job:
            return None
        removed = {
            "job": job,
            "clips": [],
            "exports": [],
            "deleted_files": 0,
        }

        def _del(data: Dict[str, Any]):
            data["gta_jobs"] = [j for j in (data.get("gta_jobs") or []) if j.get("id") != job_id]
            kept_clips = []
            for c in data.get("gta_clips") or []:
                if c.get("job_id") == job_id:
                    removed["clips"].append(dict(c))
                else:
                    kept_clips.append(c)
            data["gta_clips"] = kept_clips
            kept_exports = []
            for e in data.get("gta_exports") or []:
                if e.get("job_id") == job_id:
                    removed["exports"].append(dict(e))
                else:
                    kept_exports.append(e)
            data["gta_exports"] = kept_exports

        self.mutate(_del)
        if delete_files:
            from app.r2_compat import delete_media_url
            urls = self._collect_media_urls(*removed["clips"], *removed["exports"])
            for url in urls:
                if delete_media_url(url):
                    removed["deleted_files"] += 1
        return {
            "job_id": job_id,
            "clips_deleted": len(removed["clips"]),
            "exports_deleted": len(removed["exports"]),
            "deleted_files": removed["deleted_files"],
            "job": removed["job"],
        }

    def delete_gta_video(self, video_id: str, *, delete_files: bool = True) -> Optional[Dict[str, Any]]:
        """Delete a source video and cascade jobs that used it."""
        video = self.get_gta_video(video_id)
        if not video:
            return None
        related_jobs = []
        for j in self.list_gta_studio().get("jobs") or []:
            payload = j.get("payload") or {}
            if payload.get("video_id") == video_id:
                related_jobs.append(j.get("id"))

        cascade = []
        for jid in related_jobs:
            info = self.delete_gta_job(jid, delete_files=delete_files)
            if info:
                cascade.append(info)

        def _del(data: Dict[str, Any]):
            data["gta_videos"] = [v for v in (data.get("gta_videos") or []) if v.get("id") != video_id]

        self.mutate(_del)
        deleted_files = sum(int(c.get("deleted_files") or 0) for c in cascade)
        if delete_files:
            from app.r2_compat import delete_media_url
            if delete_media_url(video.get("url") or ""):
                deleted_files += 1
        return {
            "video_id": video_id,
            "video": video,
            "jobs_deleted": len(cascade),
            "cascaded": cascade,
            "deleted_files": deleted_files,
        }

    def create_gta_segment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        item = {
            "id": _id("gtaseg"),
            "video_id": (payload.get("video_id") or "").strip(),
            "name": (payload.get("name") or "Segment").strip(),
            "url": (payload.get("url") or "").strip(),
            "start_sec": float(payload.get("start_sec") or 0),
            "end_sec": float(payload.get("end_sec") or 0),
            "description": (payload.get("description") or "").strip(),
            "tags": tags,
            "embedding": payload.get("embedding"),
            "thumbnail_url": (payload.get("thumbnail_url") or "").strip(),
            "action_level": payload.get("action_level"),
            "setting": (payload.get("setting") or "").strip(),
            "quality_score": payload.get("quality_score"),
            "source_id": (payload.get("source_id") or "").strip(),
            "created_by": self._created_by(payload),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mutate(lambda d: d.setdefault("gta_gameplay_segments", []).append(item))
        return item

    def get_gta_segment(self, segment_id: str):
        return self._get("gta_gameplay_segments", segment_id)

    def update_gta_segment(self, segment_id: str, payload: Dict[str, Any]):
        return self._update("gta_gameplay_segments", segment_id, payload)


_store: Optional[Store] = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
