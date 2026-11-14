"""Render a single vertical streamer clip from a source window."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.studio.storage import upload_gta_path
from app.studio.streamer_clips.clip_style import normalize_clip_style
from app.studio.video_engine.caption_burn import (
    burn_captions_with_overlay,
    segments_from_fallback_text,
)
from app.studio.video_engine.ffmpeg import (
    compose_reaction_stack,
    concat_clips,
    h264_args,
    make_intro_card,
    mix_music,
    overlay_logo,
    scale_crop_vertical,
    trim_clip,
    _run,
    OUT_FPS,
    OUT_H,
    OUT_W,
)

logger = logging.getLogger(__name__)


def _zoom_vertical(
    input_path: Path,
    output_path: Path,
    *,
    zoom_peak: float = 1.12,
) -> Path:
    """Subtle zoom punch for excitement — still 9:16 output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peak = max(1.0, min(1.35, float(zoom_peak or 1.12)))
    if peak <= 1.01:
        return scale_crop_vertical(input_path, output_path)
    over_w = int(OUT_W * peak)
    over_h = int(OUT_H * peak)
    vf = (
        f"fps={OUT_FPS},"
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},setsar=1,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        *h264_args(),
        str(output_path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not output_path.exists():
        return scale_crop_vertical(input_path, output_path)
    return output_path


def render_streamer_clip(
    source_path: Path,
    *,
    start_sec: float,
    end_sec: float,
    caption_segments: Optional[List[Dict[str, Any]]] = None,
    template: str = "fullscreen_gameplay",
    apply_zoom: bool = True,
    logo_path: Optional[Path] = None,
    music_path: Optional[Path] = None,
    music_volume: float = 0.1,
    burn_captions: bool = True,
    add_intro: bool = False,
    intro_title: str = "",
    intro_subtitle: str = "",
    show_logo: bool = True,
    style: Optional[Dict[str, Any]] = None,
    brand_color: str = "#22c55e",
) -> Dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="gta_clip_"))
    cfg = normalize_clip_style({
        "template": template,
        "burn_captions": burn_captions,
        "add_intro": add_intro,
        "show_logo": show_logo,
        "apply_zoom": apply_zoom,
        **(style or {}),
    })
    try:
        cut = work / "cut.mp4"
        trim_clip(source_path, cut, start_sec, end_sec)

        vertical = work / "vertical.mp4"
        if cfg["template"] == "reaction_stack":
            compose_reaction_stack(
                cut,
                vertical,
                split_ratio=cfg["split_ratio"],
                cam_anchor=cfg["cam_anchor"],
            )
        elif cfg["template"] == "pip":
            # Corner-cam feel from a single source: slight punch + vertical
            _zoom_vertical(cut, vertical, zoom_peak=max(1.08, cfg["zoom_amount"]))
        elif cfg["apply_zoom"]:
            _zoom_vertical(cut, vertical, zoom_peak=cfg["zoom_amount"])
        else:
            scale_crop_vertical(cut, vertical)

        current = vertical
        if cfg["burn_captions"]:
            clip_dur = max(0.5, float(end_sec) - float(start_sec))
            shifted = []
            for s in caption_segments or []:
                shifted.append({
                    "start": max(0.0, float(s.get("start") or 0) - float(start_sec)),
                    "end": max(0.0, float(s.get("end") or 0) - float(start_sec)),
                    "text": s.get("text") or "",
                })
            from app.studio.analysis.highlight_scoring import clean_caption_text

            shifted = [
                {**s, "text": clean_caption_text(s.get("text") or "")}
                for s in shifted
            ]
            shifted = [s for s in shifted if s.get("text") and s["end"] > s["start"]]
            if not shifted:
                # Prefer spoken-line fallbacks only — never burn "candidate moment"
                for raw in (
                    " ".join(clean_caption_text(s.get("text") or "") for s in (caption_segments or [])),
                    intro_title,
                    cfg.get("intro_text") or "",
                ):
                    fallback = clean_caption_text(raw)
                    if not fallback:
                        continue
                    if fallback.lower() in {"highlight", "streamer highlight", "clip", "viral moment"}:
                        continue
                    shifted = segments_from_fallback_text(fallback, duration_sec=clip_dur)
                    break
            if shifted:
                captioned = work / "captioned.mp4"
                try:
                    burn_captions_with_overlay(
                        current,
                        shifted,
                        captioned,
                        caption_style=cfg["caption_style"],
                        caption_position=cfg["caption_position"],
                        caption_size=cfg["caption_size"],
                        accent_hex=brand_color or "#FACC15",
                        work_dir=work / "caps",
                    )
                    current = captioned
                except Exception as e:
                    logger.warning("[GTA] clip captions failed: %s", e)

        if cfg["show_logo"] and logo_path and logo_path.exists():
            branded = work / "branded.mp4"
            overlay_logo(
                current,
                logo_path,
                branded,
                width=cfg["logo_size"],
                position=cfg["logo_position"],
            )
            current = branded

        if cfg["use_music"] and music_path and music_path.exists():
            mixed = work / "mixed.mp4"
            vol = cfg["music_volume"] if cfg["music_volume"] is not None else music_volume
            mix_music(current, music_path, mixed, music_volume=float(vol))
            current = mixed

        pieces: List[Path] = []
        if cfg["add_intro"]:
            intro = work / "intro.mp4"
            try:
                make_intro_card(
                    intro,
                    title=(cfg.get("intro_text") or intro_title or "Highlight").strip() or "Highlight",
                    subtitle=(intro_subtitle or "").strip(),
                    duration_sec=cfg["intro_duration_sec"],
                )
                pieces.append(intro)
            except Exception as e:
                logger.warning("[GTA] intro card failed: %s", e)
        pieces.append(current)
        if cfg["add_end_card"]:
            endc = work / "endcard.mp4"
            try:
                make_intro_card(
                    endc,
                    title=(cfg.get("end_card_text") or "Follow for more").strip() or "Follow for more",
                    subtitle=(intro_subtitle or "").strip(),
                    duration_sec=min(2.2, cfg["intro_duration_sec"] + 0.3),
                )
                pieces.append(endc)
            except Exception as e:
                logger.warning("[GTA] end card failed: %s", e)

        if len(pieces) > 1:
            assembled = work / "assembled.mp4"
            try:
                concat_clips(pieces, assembled)
                current = assembled
            except Exception as e:
                logger.warning("[GTA] style concat failed: %s", e)
                current = pieces[0] if pieces[0] == current else current

        final = work / "final.mp4"
        shutil.copyfile(current, final)
        url, filename = upload_gta_path(final, content_type="video/mp4", prefix="gta_clip")
        body_dur = max(0.1, float(end_sec) - float(start_sec))
        extras = 0.0
        if cfg["add_intro"]:
            extras += float(cfg["intro_duration_sec"])
        if cfg["add_end_card"]:
            extras += min(2.2, float(cfg["intro_duration_sec"]) + 0.3)
        return {
            "url": url,
            "filename": filename,
            "duration_sec": body_dur + extras,
            "template": cfg["template"],
            "style": cfg,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
