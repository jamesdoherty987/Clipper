"""GTAClipper API — FastAPI app for local content studio."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from app.ffmpeg_utils import ffmpeg_available
from app.r2_compat import MEDIA, upload_bytes
from app.store import get_store
from app.studio.job_queue import enqueue_job

app = FastAPI(title="GTAClipper", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA)), name="media")

UPLOAD_MAX = 500 * 1024 * 1024
_EXT_TYPES = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


async def _save_upload(file: UploadFile, folder: str = "uploads") -> dict:
    if not file or not file.filename:
        raise HTTPException(400, "No file provided")
    raw = await file.read()
    if len(raw) > UPLOAD_MAX:
        raise HTTPException(400, "File too large (max 500MB)")
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin").lower()[:8]
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if not ct or ct == "application/octet-stream":
        ct = _EXT_TYPES.get(ext, "application/octet-stream")
    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"gta_{timestamp}_{secrets.token_hex(4)}.{ext}"
    url = upload_bytes(raw, filename=filename, content_type=ct, folder=folder)
    return {"url": url, "filename": file.filename, "content_type": ct, "size_bytes": len(raw)}


@app.get("/health")
def health():
    return {
        "ok": True,
        "ffmpeg": ffmpeg_available(),
        "openai": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")),
    }


@app.get("/api/overview")
def overview():
    store = get_store()
    return {
        "success": True,
        **store.get_gta_overview(),
        "providers": {
            "ffmpeg": {"configured": ffmpeg_available()},
            "openai": {"configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY"))},
        },
    }


@app.get("/api/studio")
def studio():
    return {"success": True, **get_store().list_gta_studio()}


@app.get("/api/settings")
def get_settings():
    return {"success": True, "settings": get_store().get_gta_settings()}


@app.put("/api/settings")
def put_settings(body: dict):
    return {"success": True, "settings": get_store().update_gta_settings(body or {})}


@app.get("/api/videos")
def list_videos():
    return {"success": True, "videos": get_store().list_gta_studio()["videos"]}


@app.post("/api/videos/upload")
async def upload_video(
    file: UploadFile = File(...),
    kind: str = Form("gameplay"),
    name: str = Form(""),
    tags: str = Form(""),
    source_id: str = Form(""),
    streamer_name: str = Form(""),
    created_by: str = Form("local"),
):
    uploaded = await _save_upload(file, folder="videos")
    store = get_store()
    video = store.create_gta_video({
        "name": name or uploaded["filename"],
        "kind": kind,
        "url": uploaded["url"],
        "content_type": uploaded["content_type"],
        "size_bytes": uploaded["size_bytes"],
        "source_id": source_id,
        "streamer_name": streamer_name,
        "tags": tags,
        "created_by": created_by,
    })
    return {"success": True, "video": video, **uploaded}


@app.get("/api/jobs")
def list_jobs():
    return {"success": True, "jobs": get_store().list_gta_studio()["jobs"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = get_store().get_gta_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"success": True, "job": job}


@app.get("/api/topics")
def list_topics():
    return {"success": True, "topics": get_store().list_gta_studio()["topics"]}


@app.post("/api/topics/generate")
def generate_topics(body: dict):
    from app.studio.explainers.script_generation import research_topics
    store = get_store()
    try:
        topics = research_topics(
            store,
            count=int((body or {}).get("count") or 3),
            seed=((body or {}).get("seed") or (body or {}).get("focus") or "").strip(),
            created_by=((body or {}).get("created_by") or "local").strip(),
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"success": True, "topics": topics}


@app.get("/api/scripts")
def list_scripts():
    return {"success": True, "scripts": get_store().list_gta_studio()["scripts"]}


@app.post("/api/scripts")
def create_script(body: dict):
    from app.studio.explainers.script_generation import create_script_from_topic
    store = get_store()
    body = body or {}
    try:
        if body.get("generate") or body.get("topic_id") or body.get("topic"):
            script = create_script_from_topic(
                store,
                topic_id=(body.get("topic_id") or "").strip(),
                title=(body.get("title") or "").strip(),
                topic_text=(body.get("topic") or body.get("topic_text") or "").strip(),
                hook=(body.get("hook") or "").strip(),
                target_duration_sec=int(body.get("target_duration_sec") or 45),
                notes=(body.get("notes") or "").strip(),
                created_by=(body.get("created_by") or "local").strip(),
            )
        else:
            script = store.create_gta_script(body)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"success": True, "script": script}


@app.put("/api/scripts/{script_id}")
def update_script(script_id: str, body: dict):
    script = get_store().update_gta_script(script_id, body or {})
    if not script:
        raise HTTPException(404, "Script not found")
    return {"success": True, "script": script}


@app.get("/api/recordings")
def list_recordings():
    return {"success": True, "recordings": get_store().list_gta_studio()["recordings"]}


@app.post("/api/recordings/upload")
async def upload_recording(
    file: UploadFile = File(...),
    script_id: str = Form(""),
    name: str = Form(""),
    created_by: str = Form("local"),
):
    uploaded = await _save_upload(file, folder="recordings")
    if not (uploaded["content_type"] or "").startswith("video/"):
        raise HTTPException(400, "Upload a video file (MP4 or MOV)")
    recording = get_store().create_gta_recording({
        "script_id": script_id,
        "name": name or uploaded["filename"],
        "url": uploaded["url"],
        "content_type": uploaded["content_type"],
        "size_bytes": uploaded["size_bytes"],
        "created_by": created_by,
    })
    return {"success": True, "recording": recording}


@app.post("/api/explainers/render")
def render_explainer(body: dict):
    store = get_store()
    body = body or {}
    script_id = (body.get("script_id") or "").strip()
    recording_id = (body.get("recording_id") or "").strip()
    if not script_id or not recording_id:
        raise HTTPException(400, "script_id and recording_id are required")
    if not store.get_gta_script(script_id):
        raise HTTPException(404, "Script not found")
    if not store.get_gta_recording(recording_id):
        raise HTTPException(404, "Recording not found")
    job = store.create_gta_job({
        "name": (store.get_gta_script(script_id) or {}).get("title") or "GTA explainer",
        "type": "explainer_render",
        "created_by": (body.get("created_by") or "local").strip(),
        "payload": {
            "script_id": script_id,
            "recording_id": recording_id,
            "template": (body.get("template") or "").strip(),
            "require_commercial": bool(body.get("require_commercial", True)),
        },
    })
    job = enqueue_job(store, "explainer_render", job["id"]) or job
    return {"success": True, "job": job}


@app.get("/api/exports")
def list_exports():
    return {"success": True, "exports": get_store().list_gta_studio()["exports"]}


@app.post("/api/exports/{export_id}/approve")
def approve_export(export_id: str):
    export = get_store().update_gta_export(export_id, {"status": "approved"})
    if not export:
        raise HTTPException(404, "Export not found")
    return {"success": True, "export": export}


@app.post("/api/exports/{export_id}/reject")
def reject_export(export_id: str):
    export = get_store().update_gta_export(export_id, {"status": "rejected"})
    if not export:
        raise HTTPException(404, "Export not found")
    return {"success": True, "export": export}


@app.post("/api/exports/{export_id}/email")
def email_export(export_id: str, body: dict):
    from app.email_notify import email_video
    store = get_store()
    export = store.get_gta_export(export_id)
    if not export:
        raise HTTPException(404, "Export not found")
    settings = store.get_gta_settings()
    body = body or {}
    to_email = (body.get("to_email") or body.get("email") or settings.get("notify_email") or "").strip()
    if not to_email:
        raise HTTPException(400, "Enter an email or set notify email in Settings")
    if not export.get("url"):
        raise HTTPException(400, "Export has no video URL")
    try:
        info = email_video(
            to_email=to_email,
            video_url=export["url"],
            video_name=export.get("title") or export.get("name") or "GTAClipper video",
            message=(body.get("message") or "").strip(),
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"success": True, **info}


@app.get("/api/library/segments")
def list_segments(q: str = ""):
    from app.studio.gameplay_library.search import search_segments
    store = get_store()
    if q.strip():
        segments = search_segments(store, q)
    else:
        segments = store.list_gta_studio()["segments"]
    return {"success": True, "segments": segments}


@app.post("/api/library/segments")
def create_segment(body: dict):
    from app.studio.gameplay_library.ingestion import create_segment_from_video
    store = get_store()
    body = body or {}
    try:
        if body.get("video_id"):
            segment = create_segment_from_video(
                store,
                video_id=(body.get("video_id") or "").strip(),
                name=(body.get("name") or "").strip(),
                description=(body.get("description") or "").strip(),
                tags=body.get("tags"),
                start_sec=float(body.get("start_sec") or 0),
                end_sec=float(body.get("end_sec") or 0),
                source_id=(body.get("source_id") or "").strip(),
                created_by=(body.get("created_by") or "local").strip(),
            )
        else:
            segment = store.create_gta_segment(body)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"success": True, "segment": segment}


@app.put("/api/library/segments/{segment_id}")
def update_segment(segment_id: str, body: dict):
    segment = get_store().update_gta_segment(segment_id, body or {})
    if not segment:
        raise HTTPException(404, "Segment not found")
    return {"success": True, "segment": segment}


@app.post("/api/library/ingest")
def library_ingest(body: dict):
    store = get_store()
    body = body or {}
    video_id = (body.get("video_id") or "").strip()
    if not video_id:
        raise HTTPException(400, "video_id is required")
    job = store.create_gta_job({
        "name": body.get("name") or "Library ingest",
        "type": "library_ingest",
        "created_by": (body.get("created_by") or "local").strip(),
        "payload": {
            "video_id": video_id,
            "name": body.get("name") or "",
            "description": body.get("description") or "",
            "tags": body.get("tags") or [],
            "start_sec": body.get("start_sec") or 0,
            "end_sec": body.get("end_sec") or 0,
            "source_id": body.get("source_id") or "",
        },
    })
    job = enqueue_job(store, "library_ingest", job["id"]) or job
    return {"success": True, "job": job}


@app.get("/api/sources")
def list_sources():
    return {"success": True, "sources": get_store().list_gta_studio()["sources"]}


@app.post("/api/sources")
def create_source(body: dict):
    try:
        source = get_store().create_gta_source(body or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "source": source}


@app.put("/api/sources/{source_id}")
def update_source(source_id: str, body: dict):
    source = get_store().update_gta_source(source_id, body or {})
    if not source:
        raise HTTPException(404, "Source not found")
    return {"success": True, "source": source}


@app.get("/api/clips")
def list_clips():
    return {"success": True, "clips": get_store().list_gta_studio()["clips"]}


@app.post("/api/clips/{clip_id}/approve")
def approve_clip(clip_id: str):
    clip = get_store().update_gta_clip(clip_id, {"status": "approved"})
    if not clip:
        raise HTTPException(404, "Clip not found")
    return {"success": True, "clip": clip}


@app.post("/api/clips/{clip_id}/reject")
def reject_clip(clip_id: str):
    clip = get_store().update_gta_clip(clip_id, {"status": "rejected"})
    if not clip:
        raise HTTPException(404, "Clip not found")
    return {"success": True, "clip": clip}


@app.post("/api/clips/{clip_id}/regenerate")
def regenerate_clip_route(clip_id: str, body: dict):
    from app.studio.streamer_clips.pipeline import regenerate_clip
    body = body or {}
    try:
        start = float(body.get("start_sec"))
        end = float(body.get("end_sec"))
    except (TypeError, ValueError):
        raise HTTPException(400, "start_sec and end_sec are required")
    if end <= start + 1:
        raise HTTPException(400, "end_sec must be greater than start_sec")
    try:
        clip = regenerate_clip(
            get_store(),
            clip_id,
            start_sec=start,
            end_sec=end,
            template=(body.get("template") or "").strip(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"success": True, "clip": clip}


@app.post("/api/clips/jobs")
def create_clip_job(body: dict):
    from app.studio.streamer_clips.ingestion import create_clip_job_payload, validate_clip_request
    store = get_store()
    body = body or {}
    try:
        validate_clip_request(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    video_id = (body.get("video_id") or "").strip()
    if not video_id and body.get("video_url"):
        video = store.create_gta_video({
            "name": body.get("name") or f"{body.get('streamer_name') or 'Streamer'} source",
            "kind": "streamer",
            "url": body.get("video_url"),
            "content_type": body.get("content_type") or "video/mp4",
            "size_bytes": body.get("size_bytes") or 0,
            "source_id": body.get("source_id") or "",
            "streamer_name": body.get("streamer_name") or "",
            "created_by": body.get("created_by") or "local",
        })
        video_id = video["id"]
    if body.get("source_id"):
        try:
            store.assert_gta_source_commercial_ok(body["source_id"])
        except ValueError as e:
            raise HTTPException(400, str(e))
    payload = create_clip_job_payload(
        video_id=video_id,
        streamer_name=(body.get("streamer_name") or "").strip(),
        clip_count=int(body.get("clip_count") or 8),
        target_duration_sec=int(body.get("target_duration_sec") or 30),
        template=(body.get("template") or "facecam_top").strip(),
    )
    job = store.create_gta_job({
        "name": f"{payload.get('streamer_name') or 'Streamer'} clips",
        "type": "clip_job",
        "created_by": (body.get("created_by") or "local").strip(),
        "payload": payload,
    })
    job = enqueue_job(store, "clip_job", job["id"]) or job
    return {"success": True, "job": job, "video_id": video_id}
