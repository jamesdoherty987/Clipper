"""Normalized, customizable clip style for streamer renders."""
from __future__ import annotations

from typing import Any, Dict, List


PRESETS: Dict[str, Dict[str, Any]] = {
    "clean": {
        "label": "Clean fullscreen",
        "template": "fullscreen_gameplay",
        "burn_captions": True,
        "caption_style": "clean",
        "caption_position": "bottom",
        "caption_size": "md",
        "highlight_keywords": False,
        "add_intro": False,
        "add_end_card": False,
        "show_logo": True,
        "logo_position": "top_right",
        "logo_size": 140,
        "apply_zoom": False,
        "zoom_amount": 1.08,
        "split_ratio": 0.42,
        "cam_anchor": "top_right",
        "intro_duration_sec": 1.4,
        "use_music": True,
    },
    "viral": {
        "label": "Viral captions",
        "template": "fullscreen_gameplay",
        "burn_captions": True,
        "caption_style": "viral",
        "caption_position": "center",
        "caption_size": "lg",
        "highlight_keywords": True,
        "add_intro": True,
        "add_end_card": False,
        "show_logo": True,
        "logo_position": "top_right",
        "logo_size": 150,
        "apply_zoom": True,
        "zoom_amount": 1.14,
        "split_ratio": 0.42,
        "cam_anchor": "top_right",
        "intro_duration_sec": 1.5,
        "use_music": True,
    },
    "split_reaction": {
        "label": "Reaction split",
        "template": "reaction_stack",
        "burn_captions": True,
        "caption_style": "bold",
        "caption_position": "bottom",
        "caption_size": "md",
        "highlight_keywords": True,
        "add_intro": False,
        "add_end_card": True,
        "show_logo": True,
        "logo_position": "top_left",
        "logo_size": 130,
        "apply_zoom": False,
        "zoom_amount": 1.1,
        "split_ratio": 0.42,
        "cam_anchor": "top_right",
        "intro_duration_sec": 1.4,
        "use_music": True,
    },
    "branded": {
        "label": "Branded pack",
        "template": "fullscreen_gameplay",
        "burn_captions": True,
        "caption_style": "viral",
        "caption_position": "bottom",
        "caption_size": "md",
        "highlight_keywords": True,
        "add_intro": True,
        "add_end_card": True,
        "show_logo": True,
        "logo_position": "top_right",
        "logo_size": 170,
        "apply_zoom": True,
        "zoom_amount": 1.1,
        "split_ratio": 0.4,
        "cam_anchor": "top_right",
        "intro_duration_sec": 1.8,
        "use_music": True,
    },
}

_DEFAULTS: Dict[str, Any] = {
    "preset": "viral",
    "template": "fullscreen_gameplay",
    "burn_captions": True,
    "caption_style": "viral",
    "caption_position": "bottom",
    "caption_size": "md",
    "highlight_keywords": True,
    "add_intro": False,
    "add_end_card": False,
    "show_logo": True,
    "logo_position": "top_right",
    "logo_size": 150,
    "apply_zoom": True,
    "zoom_amount": 1.12,
    "split_ratio": 0.42,
    "cam_anchor": "top_right",
    "intro_duration_sec": 1.5,
    "intro_text": "",
    "end_card_text": "",
    "use_music": True,
    "music_volume": None,
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _one_of(value: Any, options: List[str], default: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in options else default


def list_presets() -> List[Dict[str, Any]]:
    return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "label"}, "label": v["label"]} for k, v in PRESETS.items()]


def normalize_clip_style(raw: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Merge preset + overrides into a stable style dict for rendering."""
    raw = dict(raw or {})
    preset_id = str(raw.get("preset") or raw.get("style_preset") or "").strip().lower()
    base = dict(_DEFAULTS)
    if preset_id in PRESETS:
        base.update(PRESETS[preset_id])
        base["preset"] = preset_id
    elif preset_id:
        base["preset"] = "custom"
    else:
        base["preset"] = "custom"

    # Flat job payload fields also count as overrides
    for key in _DEFAULTS.keys():
        if key in raw and raw[key] is not None and raw[key] != "":
            base[key] = raw[key]
    style_block = raw.get("style") if isinstance(raw.get("style"), dict) else None
    if style_block:
        for key, val in style_block.items():
            if val is not None and val != "":
                base[key] = val

    tmpl = _one_of(
        base.get("template"),
        ["fullscreen_gameplay", "reaction_stack", "pip", "facecam_top", "split", "split_stack"],
        "fullscreen_gameplay",
    )
    if tmpl in {"facecam_top", "split", "split_stack"}:
        tmpl = "reaction_stack"

    style = {
        "preset": str(base.get("preset") or "custom"),
        "template": tmpl,
        "burn_captions": _as_bool(base.get("burn_captions"), True),
        "caption_style": _one_of(base.get("caption_style"), ["clean", "bold", "viral"], "viral"),
        "caption_position": _one_of(base.get("caption_position"), ["top", "center", "bottom"], "bottom"),
        "caption_size": _one_of(base.get("caption_size"), ["sm", "md", "lg"], "md"),
        "highlight_keywords": _as_bool(base.get("highlight_keywords"), True),
        "add_intro": _as_bool(base.get("add_intro"), False),
        "add_end_card": _as_bool(base.get("add_end_card"), False),
        "show_logo": _as_bool(base.get("show_logo"), True),
        "logo_position": _one_of(
            base.get("logo_position"),
            ["top_left", "top_right", "bottom_left", "bottom_right"],
            "top_right",
        ),
        "logo_size": int(_clamp_float(base.get("logo_size"), 80, 280, 150)),
        "apply_zoom": _as_bool(base.get("apply_zoom"), True),
        "zoom_amount": _clamp_float(base.get("zoom_amount"), 1.0, 1.35, 1.12),
        "split_ratio": _clamp_float(base.get("split_ratio"), 0.28, 0.55, 0.42),
        "cam_anchor": _one_of(
            base.get("cam_anchor"),
            ["top_left", "top_right", "top_center", "center"],
            "top_right",
        ),
        "intro_duration_sec": _clamp_float(base.get("intro_duration_sec"), 0.8, 3.5, 1.5),
        "intro_text": str(base.get("intro_text") or "").strip()[:80],
        "end_card_text": str(base.get("end_card_text") or "").strip()[:80],
        "use_music": _as_bool(base.get("use_music"), True),
        "music_volume": None
        if base.get("music_volume") in (None, "")
        else _clamp_float(base.get("music_volume"), 0.0, 1.0, 0.12),
    }
    if style["template"] != "fullscreen_gameplay":
        # Zoom only applies to fullscreen path
        style["apply_zoom"] = False
    return style
