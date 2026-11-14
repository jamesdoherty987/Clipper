"""Multi-method viral moment detection + ranking for streamer clips."""
from __future__ import annotations

import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Placeholder / junk captions that must never be burned on-screen
_BAD_CAPTION_RE = re.compile(
    r"^(candidate\s*moment|highlight|streamer\s*moment|clip\s*\d+|n/?a|null|none|"
    r"no\s*frames|vision_fallback|parse_error|moment)$",
    re.I,
)

_REACTION_KEYS = re.compile(
    r"\b(lol|lmao|omg|omfg|what|holy|no way|bro|dude|insane|crazy|oh my|wtf|haha|laugh|"
    r"crash|police|cops|chase|explode|explosion|died|dead|clip that|watch this|"
    r"are you serious|let'?s go|noooo|yooo|sheesh|bruh|dude what|wait what|"
    r"i can'?t|oh no|get out|run|jump|kill|shot|missed|clutch|gg|rage|screaming|"
    r"unbelievable|impossible|nah|fr|deadass|send it|go go go)\b",
    re.I,
)

_INTENSITY_WORDS = re.compile(
    r"\b(fuck|shit|damn|hell|stupid|idiot|kill|die|dead|crash|explode|police|"
    r"chase|run|jump|shot|miss|win|lose|fire|bomb|helicopter|tank|mad|crazy|"
    r"insane|wild|holy|wtf|omg)\b",
    re.I,
)


def _model() -> str:
    return os.getenv("GTA_SCRIPT_MODEL") or os.getenv("CHAT_MODEL") or "gpt-4o"


def _client():
    from app.openai_client import get_openai_client

    return get_openai_client()


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return json.loads(m.group(1).strip())
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("could not parse ranking JSON")


def is_placeholder_caption(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _BAD_CAPTION_RE.match(t):
        return True
    if len(t) < 3:
        return True
    return False


def clean_caption_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if is_placeholder_caption(t):
        return ""
    return t


def duration_bounds(target_duration_sec: float) -> Tuple[float, float]:
    """
    Band around the user's target.
    15s target → 10–28s (same ratios for other targets).
    """
    target = max(8.0, min(120.0, float(target_duration_sec or 30)))
    # 15 → 10..28  ⇒  lo=target*(10/15), hi=target*(28/15)
    lo = max(8.0, target * (10.0 / 15.0))
    hi = min(120.0, target * (28.0 / 15.0))
    if hi <= lo:
        hi = lo + 4.0
    return lo, hi


def preferred_clip_length(target_duration_sec: float) -> float:
    """Ideal cut length — the user's target, clamped into the allowed band."""
    lo, hi = duration_bounds(target_duration_sec)
    return max(lo, min(hi, float(target_duration_sec or lo)))


def clamp_window_to_target(
    start: float,
    end: float,
    *,
    duration_sec: float,
    target_duration_sec: float,
    peak_sec: Optional[float] = None,
    prefer_story: bool = True,
) -> Tuple[float, float]:
    """
    Keep clips near the user's target. Expand short cuts up to target;
    trim anything that overshoots the high band.
    """
    lo, hi = duration_bounds(target_duration_sec)
    duration_sec = max(1.0, float(duration_sec or 1.0))
    target = preferred_clip_length(target_duration_sec)
    start = max(0.0, float(start or 0))
    end = min(duration_sec, float(end or 0))
    if end <= start + 1:
        peak = float(peak_sec if peak_sec is not None else start)
        start = max(0.0, peak - target * 0.35)
        end = min(duration_sec, start + target)
    length = end - start
    peak = float(peak_sec if peak_sec is not None else (start + length * 0.55))
    peak = min(max(peak, 0.0), duration_sec)

    min_wanted = max(lo, target * 0.9)
    if length < min_wanted:
        pre = min_wanted * 0.35
        start = max(0.0, peak - pre)
        end = min(duration_sec, start + min_wanted)
        if end - start < min_wanted:
            start = max(0.0, end - min_wanted)
        length = end - start
    if length > hi:
        # Over the allowed band — rebuild around the peak at preferred length
        want = min(hi, max(target, lo))
        start = max(0.0, peak - want * 0.35)
        end = min(duration_sec, start + want)
        if end - start > hi:
            start = max(0.0, end - hi)
        length = end - start
    elif prefer_story:
        if peak < start + 1.0:
            shift = (start + length * 0.35) - peak
            start = max(0.0, start - shift)
            end = min(duration_sec, start + length)
        elif peak > end - 1.5:
            shift = peak - (start + length * 0.65)
            end = min(duration_sec, end + shift)
            start = max(0.0, end - length)

    if end > duration_sec:
        end = duration_sec
        start = max(0.0, end - min(hi, max(lo, length if length >= lo else target)))
    if end - start < lo and duration_sec >= lo:
        if start + lo <= duration_sec:
            end = start + lo
        else:
            end = duration_sec
            start = max(0.0, end - lo)
    # Hard cap: never exceed hi after all adjustments
    if end - start > hi:
        start = max(0.0, peak - hi * 0.35)
        end = min(duration_sec, start + hi)
        if end - start > hi:
            start = max(0.0, end - hi)
    return round(start, 2), round(end, 2)


def coerce_virality_score(*values: Any) -> float:
    """
    Normalize any score scale to 0–100.
    Fixes leaked detector scores like 0.8 / 1.1 showing as the final virality.
    """
    for raw in values:
        if raw is None or raw == "":
            continue
        try:
            n = float(raw)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        if n <= 1.5:
            # 0–1.5 detector / mistaken GPT scale → percent
            n *= 100.0
        elif n <= 10:
            # 1–10 scale
            n *= 10.0
        return float(min(100.0, max(1.0, n)))
    return 0.0


# Forced display ladder so ranked clips never cluster (e.g. all ~80).
_VIRALITY_LADDER = [97, 86, 74, 62, 51, 41, 33, 26, 22, 18]


def amplify_virality_scores(
    items: List[Dict[str, Any]],
    *,
    score_key: str = "score",
) -> List[Dict[str, Any]]:
    """
    Assign a hard rank ladder after sorting by quality.
    #1 ≈ 97, #2 ≈ 86, #3 ≈ 74… so scores always have real spread.
    """
    if not items:
        return items
    raw = [
        coerce_virality_score(
            it.get("composite_score"),
            it.get("virality_score"),
            it.get("vision_score"),
            it.get(score_key),
        )
        for it in items
    ]
    n = len(raw)
    order = sorted(range(n), key=lambda i: (raw[i], -i), reverse=True)

    for rank, i in enumerate(order):
        if rank < len(_VIRALITY_LADDER):
            ladder = float(_VIRALITY_LADDER[rank])
        else:
            ladder = max(12.0, 18.0 - (rank - len(_VIRALITY_LADDER) + 1) * 3.0)
        # Tiny absolute nudge so two equal ranks still reflect quality a bit
        abs_q = raw[i]
        if abs_q < 35:
            ladder = min(ladder, 48.0)  # weak absolute quality can't look elite
        elif abs_q >= 85 and rank == 0:
            ladder = max(ladder, 95.0)
        final = 0.88 * ladder + 0.12 * abs_q
        # Enforce minimum gap from previous assigned score
        if rank > 0:
            prev = items[order[rank - 1]][score_key]
            final = min(final, float(prev) - 8.0)
        items[i][score_key] = round(min(99.0, max(12.0, final)), 1)
        items[i]["virality_score"] = items[i][score_key]
        items[i]["rank"] = rank + 1
    return items


def fuse_av_highlight_peaks(
    *,
    audio_climaxes: List[Dict[str, Any]],
    motion_peaks: Optional[List[Dict[str, Any]]] = None,
    curve_peaks: Optional[List[Dict[str, Any]]] = None,
    top_n: int = 8,
    merge_sec: float = 4.0,
) -> List[Dict[str, Any]]:
    """
    ClipAnything-style multimodal ranking: fuse audio climax + motion + curve
    into a single ordered peak list. Speech is intentionally NOT required.
    """
    motion_peaks = motion_peaks or []
    curve_peaks = curve_peaks or []
    raw: List[Dict[str, Any]] = []
    for c in audio_climaxes or []:
        raw.append({**c, "_fuse": 3.5 + float(c.get("z_score") or c.get("score") or 0)})
    for m in motion_peaks:
        mz = float(m.get("z_score") or m.get("score") or 0)
        # Visual action alone can be the finish (KO / crash) even when crowd audio
        # peaked earlier on a non-finish exchange — weight strong motion heavily.
        motion_w = 4.2 + mz if mz >= 1.8 else 2.2 + mz
        raw.append({**m, "_fuse": motion_w})
    for p in curve_peaks:
        raw.append({**p, "_fuse": 2.0 + float(p.get("z_score") or p.get("score") or 0)})
    if not raw:
        return []

    def _src_list(c: Dict[str, Any]) -> List[str]:
        if isinstance(c.get("sources"), list) and c["sources"]:
            return [str(s) for s in c["sources"] if s]
        s = c.get("source")
        return [str(s)] if s else []

    def _kind_list(c: Dict[str, Any]) -> List[str]:
        if isinstance(c.get("kinds"), list) and c["kinds"]:
            return [str(k) for k in c["kinds"] if k]
        k = c.get("kind")
        return [str(k)] if k else []

    raw.sort(key=lambda x: float(x.get("time_sec") or 0))
    clusters: List[Dict[str, Any]] = []
    for c in raw:
        t = float(c.get("time_sec") or 0)
        if clusters and abs(t - float(clusters[-1]["time_sec"])) < merge_sec:
            prev = clusters[-1]
            prev["_fuse"] = float(prev.get("_fuse") or 0) + float(c.get("_fuse") or 0) * 0.85
            prev["sources"] = list({*(prev.get("sources") or []), *_src_list(c)})
            prev["kinds"] = list({*(prev.get("kinds") or []), *_kind_list(c)})
            # Prefer climax timestamp as cluster center
            if c.get("climax") or c.get("source") == "audio_climax" or c.get("global_max"):
                prev["time_sec"] = round(t, 2)
                prev["climax"] = True
                prev["global_max"] = bool(prev.get("global_max") or c.get("global_max"))
                for k in ("z_score", "rms", "peak", "excitement", "score"):
                    if c.get(k) is not None:
                        prev[k] = c.get(k)
            elif float(c.get("_fuse") or 0) > float(prev.get("_best") or 0):
                prev["time_sec"] = round((float(prev["time_sec"]) + t) / 2.0, 2)
            prev["_best"] = max(float(prev.get("_best") or 0), float(c.get("_fuse") or 0))
            if "motion" in (prev.get("sources") or []) and (
                "audio_climax" in (prev.get("sources") or []) or prev.get("climax")
            ):
                prev["_fuse"] = float(prev["_fuse"]) + 2.5
                prev["av_fused"] = True
        else:
            src = c.get("source") or "mixed"
            kind = c.get("kind") or src
            clusters.append({
                **{k: v for k, v in c.items() if not str(k).startswith("_")},
                "time_sec": round(t, 2),
                "sources": _src_list(c) or [src],
                "kinds": _kind_list(c) or [kind],
                "climax": bool(
                    c.get("climax") or src == "audio_climax" or kind == "climax_impact"
                ),
                "global_max": bool(c.get("global_max")),
                "_fuse": float(c.get("_fuse") or 0),
                "_best": float(c.get("_fuse") or 0),
            })

    for c in clusters:
        c.pop("_best", None)
        if c.get("global_max"):
            c["_fuse"] = float(c.get("_fuse") or 0) + 4.0
        c["fuse_score"] = round(float(c.get("_fuse") or 0), 3)
        c.pop("_fuse", None)

    clusters.sort(
        key=lambda x: (
            1 if x.get("global_max") else 0,
            1 if x.get("av_fused") else 0,
            1 if "motion" in (x.get("sources") or []) and float(x.get("z_score") or 0) >= 1.8 else 0,
            float(x.get("fuse_score") or 0),
            float(x.get("z_score") or 0),
        ),
        reverse=True,
    )
    return clusters[: max(1, top_n)]


def windows_overlap(a0: float, a1: float, b0: float, b1: float, *, pad: float = 1.5) -> bool:
    return not (a1 <= b0 + pad or a0 >= b1 - pad)


def prioritize_candidates(
    candidates: List[Dict[str, Any]],
    *,
    limit: int,
    must_include: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Prefer climax/audio/transcript/gpt peaks over sparse coverage/scene hits.
    must_include peaks are always kept (e.g. loudest climax impacts).
    """
    def _priority(c: Dict[str, Any]) -> Tuple[float, float]:
        sources = {str(s) for s in (c.get("sources") or []) if s}
        kinds = {str(k) for k in (c.get("kinds") or []) if k}
        weak_only = sources <= {"interval", "scene", "coverage", "fallback"} or not sources
        strong = sources & {
            "audio", "audio_jump", "audio_climax", "audio_curve", "motion",
            "transcript_reaction", "transcript_intensity", "transcript_burst",
            "gpt_transcript", "transcript",
        }
        score = float(c.get("score") or 0)
        boost = 0.0
        boost += 2.8 * len(strong)
        boost += 1.6 * max(0, len(sources) - 1)
        if c.get("text"):
            boost += 1.2
        if c.get("climax") or "audio_climax" in sources or "climax_impact" in kinds:
            boost += 6.0
            score = max(score, 1.4)
        if "motion" in sources and ("audio_climax" in sources or "audio" in sources):
            boost += 2.5  # AV fusion bonus (sports highlight papers)
        if weak_only:
            boost -= 4.0
            score *= 0.35
        if "gpt_transcript" in sources:
            boost += 2.0
        return (score + boost, score)

    ranked = sorted(candidates or [], key=_priority, reverse=True)
    out: List[Dict[str, Any]] = []
    used: List[float] = []

    # Pin mandatory climax peaks first
    for c in must_include or []:
        t = float(c.get("time_sec") or 0)
        if any(abs(t - u) < 6 for u in used):
            continue
        out.append(c)
        used.append(t)

    for c in ranked:
        if len(out) >= max(1, int(limit)):
            break
        t = float(c.get("time_sec") or 0)
        if any(abs(t - u) < 5.5 for u in used):
            continue
        out.append(c)
        used.append(t)
    return out


def merge_candidates(
    *,
    audio: List[Dict[str, Any]],
    scenes: List[Dict[str, Any]],
    transcript_peaks: List[Dict[str, Any]],
    duration_sec: float,
    max_candidates: int = 40,
    extra: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Cluster nearby signals from many detectors into highlight centers."""
    raw: List[Dict[str, Any]] = []
    for a in audio or []:
        raw.append({**a, "weight": float(a.get("weight") or 1.25)})
    for s in scenes or []:
        raw.append({**s, "weight": float(s.get("weight") or 0.5)})
    for t in transcript_peaks or []:
        raw.append({**t, "weight": float(t.get("weight") or 1.15)})
    for e in extra or []:
        raw.append({**e, "weight": float(e.get("weight") or 1.0)})

    raw = [c for c in raw if 0 <= float(c.get("time_sec") or 0) <= max(0.0, duration_sec - 1)]
    raw.sort(key=lambda x: float(x.get("time_sec") or 0))

    clusters: List[Dict[str, Any]] = []
    for c in raw:
        t = float(c.get("time_sec") or 0)
        is_climax = bool(
            c.get("climax")
            or c.get("source") == "audio_climax"
            or c.get("kind") == "climax_impact"
        )
        z = 0.0
        try:
            z = float(c.get("z_score") or 0)
        except (TypeError, ValueError):
            z = 0.0
        if clusters and abs(t - clusters[-1]["time_sec"]) < 5.5:
            prev = clusters[-1]
            w = float(c.get("weight") or 1)
            prev["score"] = float(prev.get("score") or 0) + float(c.get("score") or 0.4) * w
            prev["sources"].append(c.get("source") or "mixed")
            prev["kinds"].append(c.get("kind") or c.get("source") or "")
            # Bias cluster center toward higher-weight signals
            # Keep climax centers locked near the impact (don't drift into chatter)
            prev_w = max(0.1, float(prev.get("_wsum") or 1))
            if is_climax and w >= float(prev.get("_wsum") or 1):
                prev["time_sec"] = round(t, 2)
            else:
                prev["time_sec"] = round((prev["time_sec"] * prev_w + t * w) / (prev_w + w), 2)
            prev["_wsum"] = prev_w + w
            if is_climax:
                prev["climax"] = True
            if z > float(prev.get("z_score") or 0):
                prev["z_score"] = z
            if c.get("text") and (
                not prev.get("text")
                or len(str(c.get("text") or "")) > len(str(prev.get("text") or ""))
            ):
                prev["text"] = c.get("text")
            # Diversity bonus when multiple detectors agree
            uniq = {str(s) for s in prev["sources"] if s}
            if len(uniq) >= 2:
                prev["score"] = float(prev["score"]) * (1.0 + 0.12 * min(3, len(uniq) - 1))
        else:
            clusters.append({
                "time_sec": round(t, 2),
                "score": float(c.get("score") or 0.4) * float(c.get("weight") or 1),
                "sources": [c.get("source") or "mixed"],
                "kinds": [c.get("kind") or c.get("source") or ""],
                "text": clean_caption_text(c.get("text") or ""),
                "climax": is_climax,
                "z_score": z,
                "_wsum": float(c.get("weight") or 1),
            })

    for c in clusters:
        c.pop("_wsum", None)
        sources = {str(s) for s in (c.get("sources") or []) if s}
        kinds = {str(k) for k in (c.get("kinds") or []) if k}
        if "audio_climax" in sources or "climax_impact" in kinds:
            c["climax"] = True
        # Normalize score into a rough 0–100-ish band for later merge with vision
        c["score"] = round(float(c.get("score") or 0), 3)

    clusters.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return clusters[:max_candidates]


def transcript_reaction_peaks(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Heuristic: laughter / swearing / hype words in transcript."""
    out = []
    for s in segments or []:
        text = s.get("text") or ""
        if not _REACTION_KEYS.search(text):
            continue
        start = float(s.get("start") or 0)
        hits = len(_REACTION_KEYS.findall(text))
        out.append({
            "time_sec": round(start, 2),
            "score": min(1.4, 0.75 + 0.2 * hits),
            "kind": "reaction_line",
            "source": "transcript_reaction",
            "weight": 1.2,
            "text": clean_caption_text(text)[:200],
        })
    return out


def transcript_intensity_peaks(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score segments by intensity words, caps, and punctuation energy."""
    out = []
    for s in segments or []:
        text = (s.get("text") or "").strip()
        if len(text) < 4:
            continue
        score = 0.0
        score += 0.18 * len(_INTENSITY_WORDS.findall(text))
        score += 0.12 * text.count("!")
        score += 0.08 * text.count("?")
        caps = sum(1 for w in text.split() if len(w) > 2 and w.isupper())
        score += 0.1 * caps
        if score < 0.35:
            continue
        out.append({
            "time_sec": round(float(s.get("start") or 0), 2),
            "score": min(1.5, score),
            "kind": "intensity",
            "source": "transcript_intensity",
            "weight": 1.0,
            "text": clean_caption_text(text)[:200],
        })
    return out


def transcript_speech_bursts(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dense talking after a pause — often a reaction or punchline."""
    segs = sorted(
        [
            {
                "start": float(s.get("start") or 0),
                "end": float(s.get("end") or s.get("start") or 0),
                "text": (s.get("text") or "").strip(),
            }
            for s in (segments or [])
            if (s.get("text") or "").strip()
        ],
        key=lambda x: x["start"],
    )
    out = []
    for i, s in enumerate(segs):
        gap = 0.0 if i == 0 else max(0.0, s["start"] - segs[i - 1]["end"])
        words = len(s["text"].split())
        # Burst: pause then a quick dense line, or a rapid multi-line cluster
        cluster_words = words
        cluster_end = s["end"]
        for j in range(i + 1, min(i + 4, len(segs))):
            if segs[j]["start"] - cluster_end > 1.2:
                break
            cluster_words += len(segs[j]["text"].split())
            cluster_end = segs[j]["end"]
        score = 0.0
        if gap >= 1.8 and words >= 4:
            score += 0.7
        if cluster_words >= 14 and (cluster_end - s["start"]) <= 6.0:
            score += 0.55
        if score < 0.55:
            continue
        out.append({
            "time_sec": round(s["start"], 2),
            "score": min(1.4, score),
            "kind": "speech_burst",
            "source": "transcript_burst",
            "weight": 0.95,
            "text": clean_caption_text(s["text"])[:200],
        })
    return out


def _compact_transcript(
    segments: List[Dict[str, Any]],
    *,
    max_segments: int = 220,
    focus_times: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Keep the transcript usable in a prompt; densify near audio/scene focus times."""
    segs = [
        {
            "start": round(float(s.get("start") or 0), 1),
            "end": round(float(s.get("end") or s.get("start") or 0), 1),
            "text": (s.get("text") or "").strip()[:200],
        }
        for s in (segments or [])
        if (s.get("text") or "").strip()
    ]
    if len(segs) <= max_segments:
        return segs
    focuses = [float(t) for t in (focus_times or []) if t is not None]
    # Always keep segments near focus peaks; subsample the rest evenly
    keep_idx = set()
    for t in focuses:
        for i, s in enumerate(segs):
            if abs(((s["start"] + s["end"]) / 2) - t) <= 12.0:
                keep_idx.add(i)
    # Even coverage across the whole video
    step = max(1, len(segs) // max(1, max_segments // 2))
    for i in range(0, len(segs), step):
        keep_idx.add(i)
    keep_idx.add(0)
    keep_idx.add(len(segs) - 1)
    ordered = sorted(keep_idx)
    if len(ordered) > max_segments:
        # Prefer focus-near indices
        focus_near = [i for i in ordered if any(abs(((segs[i]["start"] + segs[i]["end"]) / 2) - t) <= 12 for t in focuses)]
        filler = [i for i in ordered if i not in focus_near]
        need = max_segments - min(len(focus_near), max_segments)
        pick = focus_near[:max_segments]
        if need > 0:
            stride = max(1, len(filler) // max(1, need))
            pick.extend(filler[::stride][:need])
        ordered = sorted(set(pick))[:max_segments]
    return [segs[i] for i in ordered]


def _script_dump(
    segments: List[Dict[str, Any]],
    *,
    max_chars: int = 28000,
) -> str:
    """Huge readable timed script for the model (not a tiny sample)."""
    lines: List[str] = []
    total = 0
    for s in segments or []:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        start = float(s.get("start") or 0)
        mm = int(start // 60)
        ss = int(start % 60)
        line = f"[{mm:02d}:{ss:02d}] {text}"
        if total + len(line) + 1 > max_chars:
            lines.append("…[transcript truncated]…")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def gpt_timeline_highlight_scan(
    segments: List[Dict[str, Any]],
    *,
    streamer_name: str = "",
    video_title: str = "",
    video_context: str = "",
    max_moments: int = 12,
    duration_sec: float = 0,
    target_duration_sec: float = 30,
    audio_events: Optional[List[Dict[str, Any]]] = None,
    scene_events: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Dump a large timed script + full product/video briefing into the model and ask
    for THE main climax first, then other viral moments (Opus ClipAnything style).
    """
    audio_events = audio_events or []
    scene_events = scene_events or []
    focus_times = [float(a.get("time_sec") or 0) for a in audio_events[:50]]
    focus_times += [float(s.get("time_sec") or 0) for s in scene_events[:30]]
    # Short VODs: send nearly everything. Long VODs: still a very large chunk.
    dur = float(duration_sec or 0)
    max_segs = 900 if dur <= 900 else (500 if dur <= 2400 else 320)
    compact = _compact_transcript(segments, max_segments=max_segs, focus_times=focus_times)
    script_text = _script_dump(segments, max_chars=32000 if dur <= 900 else 22000)

    def _audio_rank_key(a: Dict[str, Any]) -> Tuple[int, float]:
        climax = 1 if (
            a.get("climax")
            or a.get("source") == "audio_climax"
            or a.get("kind") == "climax_impact"
            or a.get("source") == "motion"
        ) else 0
        return (climax, float(a.get("z_score") or a.get("score") or 0))

    audio_compact = [
        {
            "time_sec": round(float(a.get("time_sec") or 0), 1),
            "kind": a.get("kind") or a.get("source") or "audio",
            "strength": round(float(a.get("z_score") or a.get("score") or 0), 2),
            "climax": bool(
                a.get("climax")
                or a.get("source") == "audio_climax"
                or a.get("kind") == "climax_impact"
            ),
            "motion": bool(a.get("source") == "motion" or a.get("kind") == "motion_burst"),
        }
        for a in sorted(audio_events, key=_audio_rank_key, reverse=True)[:50]
    ]
    scene_compact = [
        {"time_sec": round(float(s.get("time_sec") or 0), 1)}
        for s in (scene_events or [])[:40]
    ]

    if len(compact) < 2 and not audio_compact and not script_text.strip():
        return []

    lo, hi = duration_bounds(target_duration_sec)
    preferred = preferred_clip_length(target_duration_sec)
    user_ctx = (video_context or "").strip()
    briefing = (
        "PRODUCT / GOAL\n"
        "You are the clip scout for GTAClipper (also used for sports, streams, podcasts, etc.).\n"
        "The user uploads ONE long video and wants short vertical clips for TikTok / Shorts / Reels.\n"
        "They care most about THE main moment of the video — the climax / finish / payoff a stranger "
        "would stop scrolling for — not random loud bits or intros.\n"
        "Then fill remaining slots with other distinct high-value moments.\n\n"
        "THIS VIDEO\n"
        f"- Title: {video_title or 'unknown'}\n"
        f"- Creator / name on the project: {streamer_name or 'unknown'}\n"
        f"- Duration: {round(dur, 1)}s\n"
        f"- What the user said this video is / what to look for:\n"
        f"  {(user_ctx if user_ctx else '(none — infer from the title + full script below)')}\n"
        f"- Desired clip length: ~{preferred:.0f}s (allowed {lo:.0f}–{hi:.0f}s)\n"
    )
    prompt = (
        f"{briefing}\n"
        "YOUR JOB\n"
        "1) Read the FULL timed script carefully.\n"
        "2) Use the title + user notes to understand what 'the main moment' means for THIS video "
        "(e.g. the fight finish, the punchline, the win, the reveal — whatever the story is).\n"
        "3) Pick main_moment = the single best climax/payoff timestamp.\n"
        "4) Then pick more distinct viral moments (not duplicates of the main one).\n\n"
        "RULES\n"
        "- Do NOT invent timestamps outside the script / audio timeline.\n"
        "- If speech is sparse, lean on AUDIO/MOTION peaks that line up with the story climax "
        "(crowd roar after a finish, impact + reaction). Loud mid-fight noise is NOT automatically the climax.\n"
        "- Prefer hook → brief setup → payoff → reaction.\n"
        "- Skip intros, ads, filler, dead air.\n"
        f"- Return up to {max_moments} other moments AFTER main_moment.\n"
        "- score 0–100 with real spread (main should be ~92–99 if it's clearly the climax).\n"
        "- caption: short quote or 3–6 word stake line. Never 'candidate moment'.\n\n"
        f"AUDIO / MOTION PEAKS (hints — not always the answer):\n"
        f"{json.dumps(audio_compact, ensure_ascii=False)}\n\n"
        f"SCENE CHANGES:\n{json.dumps(scene_compact, ensure_ascii=False)}\n\n"
        f"FULL TIMED SCRIPT:\n{script_text or '(no speech transcribed — use audio/motion + title/context)'}\n\n"
        f"TIMED SEGMENTS (JSON, dense):\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        "Return JSON only:\n"
        '{"main_moment":{"time_sec":0,"start_sec":0,"end_sec":20,"score":0-100,'
        '"title":"","caption":"","reason":"why this is THE main climax","hook":"","payoff":""},'
        '"moments":[{"time_sec":0,"start_sec":0,"end_sec":20,"score":0-100,'
        '"title":"","caption":"","reason":"","hook":"","payoff":""}]}'
    )
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert short-form clip editor. "
                        "You read the user's goal + a huge timed script + audio/motion hints, "
                        "then pick THE main climax of that specific video first. "
                        "Genre-agnostic. JSON only. Never invent timestamps."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if not isinstance(data, dict):
            data = {"moments": data if isinstance(data, list) else []}

        def _pack(m: Dict[str, Any], *, is_main: bool) -> Optional[Dict[str, Any]]:
            if not isinstance(m, dict):
                return None
            t = float(m.get("time_sec") or m.get("start_sec") or 0)
            if t < 0 or (duration_sec and t > float(duration_sec) + 1):
                return None
            caption = clean_caption_text(m.get("caption") or "")
            start = float(m["start_sec"]) if m.get("start_sec") is not None else None
            end = float(m["end_sec"]) if m.get("end_sec") is not None else None
            if start is not None and end is not None:
                start, end = clamp_window_to_target(
                    start,
                    end,
                    duration_sec=float(duration_sec or end + 1),
                    target_duration_sec=float(target_duration_sec),
                    peak_sec=t,
                    prefer_story=True,
                )
            raw_score = float(m.get("score") or (96 if is_main else 50))
            return {
                "time_sec": round(t, 2),
                "score": min(2.2, max(0.5, raw_score / 45.0)),
                "kind": "gpt_main" if is_main else "gpt_timeline",
                "source": "gpt_transcript",
                "weight": 3.2 if is_main else 1.7,
                "text": caption or clean_caption_text(m.get("hook") or "")[:200],
                "title": clean_caption_text(m.get("title") or ""),
                "caption": caption,
                "reason": (m.get("reason") or "").strip(),
                "hook": (m.get("hook") or "").strip(),
                "payoff": (m.get("payoff") or "").strip(),
                "start_sec": start,
                "end_sec": end,
                "is_main": is_main,
                "climax": True if is_main else bool(raw_score >= 85),
                "reserved": True if is_main else False,
                "gpt_main": is_main,
            }

        out: List[Dict[str, Any]] = []
        main = _pack(data.get("main_moment") or {}, is_main=True)
        if main:
            out.append(main)
        moments = data.get("moments") if isinstance(data.get("moments"), list) else []
        for m in moments:
            packed = _pack(m, is_main=False)
            if not packed:
                continue
            if main and abs(float(packed["time_sec"]) - float(main["time_sec"])) < 8:
                continue
            out.append(packed)
        return out[: max_moments + (1 if main else 0)]
    except Exception as e:
        logger.warning("[GTA] gpt timeline scan failed: %s", e)
        return []


def gpt_transcript_viral_scan(
    segments: List[Dict[str, Any]],
    *,
    streamer_name: str = "",
    max_moments: int = 12,
    duration_sec: float = 0,
    video_title: str = "",
    video_context: str = "",
    target_duration_sec: float = 30,
    audio_events: Optional[List[Dict[str, Any]]] = None,
    scene_events: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Back-compat wrapper → timeline highlight scan."""
    return gpt_timeline_highlight_scan(
        segments,
        streamer_name=streamer_name,
        video_title=video_title,
        video_context=video_context,
        max_moments=max_moments,
        duration_sec=duration_sec,
        target_duration_sec=target_duration_sec,
        audio_events=audio_events,
        scene_events=scene_events,
    )


def snap_window_to_transcript(
    start: float,
    end: float,
    segments: List[Dict[str, Any]],
    *,
    duration_sec: float,
    target_duration_sec: float,
    peak_sec: Optional[float] = None,
) -> Tuple[float, float]:
    """
    Expand/shrink to sentence boundaries so the clip starts and ends cleanly.
    Allows longer windows when the viral story needs setup + reaction.
    """
    lo, hi = duration_bounds(target_duration_sec)
    duration_sec = max(float(duration_sec or 0), 1.0)
    start = max(0.0, float(start))
    end = min(duration_sec, float(end))
    if end <= start + 3:
        end = min(duration_sec, start + max(lo, float(target_duration_sec or lo)))

    segs = sorted(
        [
            {
                "start": float(s.get("start") or 0),
                "end": float(s.get("end") or s.get("start") or 0),
                "text": (s.get("text") or "").strip(),
            }
            for s in (segments or [])
            if (s.get("text") or "").strip()
        ],
        key=lambda x: x["start"],
    )

    if segs:
        prior = [s for s in segs if s["start"] <= start + 0.4]
        if prior:
            idx = len(prior) - 1
            cand_start = prior[idx]["start"]
            for back in range(1, 4):
                if idx - back < 0:
                    break
                trial = prior[idx - back]["start"]
                if end - trial <= hi * 1.08:
                    cand_start = trial
            start = cand_start

        later = [s for s in segs if s["end"] >= end - 0.5]
        if later:
            cand_end = later[0]["end"]
            for fwd in later[:5]:
                if fwd["end"] - start <= hi:
                    cand_end = fwd["end"]
                else:
                    break
            end = min(duration_sec, cand_end)
        else:
            covering = [s for s in segs if s["start"] < end]
            if covering:
                end = min(duration_sec, max(end, covering[-1]["end"]))

    length = end - start
    preferred = preferred_clip_length(target_duration_sec)
    min_wanted = max(lo, preferred * 0.92)
    if length < min_wanted:
        need = min_wanted - length
        start = max(0.0, start - need * 0.4)
        end = min(duration_sec, end + need * 0.6)
        length = end - start
        if length < min_wanted:
            end = min(duration_sec, start + min_wanted)
            if end - start < min_wanted:
                start = max(0.0, end - min_wanted)
    elif length > hi:
        center = float(peak_sec if peak_sec is not None else (start + length * 0.6))
        start = max(0.0, center - hi * 0.4)
        end = min(duration_sec, start + hi)
        if end - start > hi:
            start = max(0.0, end - hi)

    if end <= start + 3:
        end = min(duration_sec, start + min_wanted)
    return clamp_window_to_target(
        start,
        end,
        duration_sec=duration_sec,
        target_duration_sec=target_duration_sec,
        peak_sec=peak_sec if peak_sec is not None else (start + end) / 2,
        prefer_story=True,
    )


def refine_window_for_candidate(
    c: Dict[str, Any],
    *,
    duration_sec: float,
    target_duration_sec: float,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[float, float]:
    """Build a natural window from vision offsets + transcript sense."""
    lo, hi = duration_bounds(target_duration_sec)
    preferred = preferred_clip_length(target_duration_sec)
    center = float(c.get("time_sec") or 0)
    sources = {str(s) for s in (c.get("sources") or []) if s}
    kinds = {str(k) for k in (c.get("kinds") or []) if k}
    is_climax = bool(
        c.get("climax")
        or "audio_climax" in sources
        or "climax_impact" in kinds
    )
    start_off = float(
        c.get("good_start_offset_sec")
        if c.get("good_start_offset_sec") is not None
        else -max(4.0, preferred * 0.35)
    )
    end_off = float(
        c.get("good_end_offset_sec")
        if c.get("good_end_offset_sec") is not None
        else max(8.0, preferred * 0.7)
    )
    # Keep offsets proportional to the requested clip length
    max_pre = min(preferred * 0.45, hi * 0.45)
    max_post = min(preferred * 0.75, hi * 0.75)
    start_off = max(-max_pre, min(-1.5, start_off))
    end_off = max(4.0, min(max_post, end_off))
    # Impact peaks need setup BEFORE the hit and reaction AFTER — lock to peak
    if is_climax:
        start_off = -max(5.0, preferred * 0.38)
        end_off = max(7.0, preferred * 0.62)

    if c.get("start_sec") is not None and c.get("end_sec") is not None and not is_climax:
        start = float(c["start_sec"])
        end = float(c["end_sec"])
    else:
        start = max(0.0, center + start_off)
        end = min(float(duration_sec), center + end_off)

    # Always aim for at least the preferred target length
    if end - start < preferred:
        need = preferred - (end - start)
        start = max(0.0, start - need * 0.38)
        end = min(float(duration_sec), end + need * 0.62)

    # Don't let sparse commentary yank an impact peak into the wrong beat
    if not is_climax:
        start, end = snap_window_to_transcript(
            start,
            end,
            segments or [],
            duration_sec=duration_sec,
            target_duration_sec=target_duration_sec,
            peak_sec=center,
        )
    return clamp_window_to_target(
        start,
        end,
        duration_sec=duration_sec,
        target_duration_sec=target_duration_sec,
        peak_sec=center,
        prefer_story=True,
    )


def dimensional_virality_scores(c: Dict[str, Any]) -> Dict[str, float]:
    """
    EchoWave / Opus-style named sub-scores (each ~0–20 → total ~0–100).
    Hook, Emotion, Payoff, Standalone, Energy.
    """
    sources = {str(s) for s in (c.get("sources") or []) if s}
    kinds = {str(k) for k in (c.get("kinds") or []) if k}
    is_climax = bool(
        c.get("climax") or "audio_climax" in sources or "climax_impact" in kinds
    )
    snip = clean_caption_text(c.get("transcript_snip") or c.get("text") or "")
    z = 0.0
    try:
        z = float(c.get("z_score") or 0)
    except (TypeError, ValueError):
        z = 0.0

    def _axis(name: str, fallback: float) -> float:
        raw = c.get(name)
        try:
            if raw is not None and raw != "":
                return max(0.0, min(20.0, float(raw)))
        except (TypeError, ValueError):
            pass
        return max(0.0, min(20.0, fallback))

    # Fallbacks from detectors when vision didn't fill axes
    energy_fb = 6.0
    if "motion" in sources:
        energy_fb += 4.0
    if "audio" in sources or "audio_jump" in sources or "audio_curve" in sources:
        energy_fb += 3.5
    if is_climax:
        energy_fb = max(energy_fb, 14.0 + min(5.0, z))
    emotion_fb = 5.0 + min(8.0, len(_REACTION_KEYS.findall(snip)) * 2.0) if snip else (12.0 if is_climax else 4.0)
    payoff_fb = 14.0 if is_climax else (8.0 if (c.get("payoff") or "").strip() else 4.0)
    if c.get("entertaining"):
        payoff_fb = max(payoff_fb, 10.0)
    hook_fb = 8.0 if (c.get("hook") or "").strip() else (7.0 if is_climax else 4.0)
    standalone_fb = 10.0 if (snip or is_climax) else 5.0
    if c.get("entertaining"):
        standalone_fb = max(standalone_fb, 11.0)

    return {
        "hook_score": _axis("hook_score", hook_fb),
        "emotion_score": _axis("emotion_score", emotion_fb),
        "payoff_score": _axis("payoff_score", payoff_fb),
        "standalone_score": _axis("standalone_score", standalone_fb),
        "energy_score": _axis("energy_score", energy_fb),
    }


def composite_virality_score(c: Dict[str, Any]) -> float:
    """
    Blend detector agreement + vision + named sub-scores into one 0–100 score.
    Pattern matches production clippers: Hook/Emotion/Payoff/Standalone/Energy.
    """
    vision = coerce_virality_score(c.get("virality_score"), c.get("vision_score"))
    base = coerce_virality_score(c.get("score"))
    if base <= 0:
        try:
            raw = float(c.get("score") or 0)
            base = min(70.0, raw * 40.0) if 0 < raw <= 5 else 0.0
        except (TypeError, ValueError):
            base = 0.0
    sources = {str(s) for s in (c.get("sources") or []) if s}
    kinds = {str(k) for k in (c.get("kinds") or []) if k}
    strong = sources & {
        "audio", "audio_jump", "audio_climax", "audio_curve", "motion",
        "transcript_reaction", "transcript_intensity", "transcript_burst",
        "gpt_transcript", "transcript",
    }
    weak_only = bool(sources) and not strong
    is_climax = bool(
        c.get("climax")
        or "audio_climax" in sources
        or "climax_impact" in kinds
    )
    z = 0.0
    try:
        z = float(c.get("z_score") or 0)
    except (TypeError, ValueError):
        z = 0.0

    dims = dimensional_virality_scores(c)
    dim_total = sum(dims.values())  # ~0–100

    # Harsh calibration: mediocre vision shouldn't float mid-80s
    if vision > 0:
        if vision < 45:
            vision *= 0.55
        elif vision < 65:
            vision = 35 + (vision - 45) * 0.9
        elif vision < 80:
            vision = 55 + (vision - 65) * 1.1
        else:
            vision = min(100.0, 78 + (vision - 80) * 1.35)

    diversity = min(24.0, 7.5 * len(strong) + 2.5 * max(0, len(sources) - 1))
    # Audio+visual agreement is the gold standard in sports highlight research
    if "motion" in sources and ({"audio", "audio_jump", "audio_climax", "audio_curve"} & sources):
        diversity = min(28.0, diversity + 8.0)
    if weak_only and not is_climax:
        diversity = min(diversity, 4.0)
        vision *= 0.7
        base *= 0.5

    entertaining = 10.0 if c.get("entertaining") else (-4.0 if is_climax else -16.0)
    snip = clean_caption_text(c.get("transcript_snip") or c.get("text") or "")
    has_text = 4.0 if snip else (1.5 if is_climax else -3.0)
    reaction_hits = len(_REACTION_KEYS.findall(snip)) if snip else 0
    reaction_bonus = min(10.0, reaction_hits * 2.8)
    climax_bonus = 0.0
    if is_climax:
        climax_bonus = 14.0 + min(14.0, max(0.0, z) * 3.2)

    blended = (
        dim_total * 0.42
        + vision * 0.28
        + base * 0.08
        + diversity
        + entertaining
        + has_text
        + reaction_bonus
        + climax_bonus
    )
    # Cap boring moments — but don't bury audio climaxes without speech
    if not c.get("entertaining") and vision < 60 and not is_climax and dims["payoff_score"] < 10:
        blended = min(blended, 42.0)
    if is_climax:
        blended = max(blended, 64.0)
    # Persist dims for UI / GPT
    c.setdefault("hook_score", dims["hook_score"])
    c.setdefault("emotion_score", dims["emotion_score"])
    c.setdefault("payoff_score", dims["payoff_score"])
    c.setdefault("standalone_score", dims["standalone_score"])
    c.setdefault("energy_score", dims["energy_score"])
    return round(min(100.0, max(0.0, blended)), 2)


def snap_window_to_silence(
    start: float,
    end: float,
    silences: List[Dict[str, Any]],
    *,
    duration_sec: float,
    peak_sec: Optional[float] = None,
    max_nudge_sec: float = 1.8,
) -> Tuple[float, float]:
    """Nudge in/out points toward nearby quiet gaps (natural cuts)."""
    if not silences:
        return start, end
    duration_sec = max(1.0, float(duration_sec or 1.0))
    start = max(0.0, float(start))
    end = min(duration_sec, float(end))
    peak = float(peak_sec if peak_sec is not None else (start + end) / 2)

    def _nearest_edge(t: float, prefer: str) -> float:
        best = t
        best_d = max_nudge_sec + 1
        for s in silences:
            a = float(s.get("start_sec") or 0)
            b = float(s.get("end_sec") or a)
            mid = (a + b) / 2
            # Prefer cutting inside the silence
            cand = mid if prefer == "mid" else (b if prefer == "end" else a)
            d = abs(cand - t)
            if d < best_d and d <= max_nudge_sec:
                # Don't pull past the peak
                if prefer == "start" and cand > peak - 0.4:
                    continue
                if prefer == "end" and cand < peak + 0.4:
                    continue
                best = cand
                best_d = d
        return best

    start = _nearest_edge(start, "start")
    end = _nearest_edge(end, "end")
    if end <= start + 3:
        return max(0.0, float(start)), min(duration_sec, float(end if end > start else start + 8))
    return round(start, 2), round(end, 2)


def gpt_rank_clips(
    candidates: List[Dict[str, Any]],
    *,
    streamer_name: str = "",
    video_title: str = "",
    video_context: str = "",
    target_count: int = 8,
    target_duration_sec: int = 30,
    video_duration_sec: float = 0,
) -> List[Dict[str, Any]]:
    """Ask GPT to pick the most viral, self-contained clip windows."""
    if not candidates:
        return []
    lo, hi = duration_bounds(target_duration_sec)
    preferred = preferred_clip_length(target_duration_sec)
    def _is_climax(c: Dict[str, Any]) -> bool:
        sources = {str(s) for s in (c.get("sources") or []) if s}
        kinds = {str(k) for k in (c.get("kinds") or []) if k}
        return bool(
            c.get("climax")
            or "audio_climax" in sources
            or "climax_impact" in kinds
        )

    # Pre-filter: promising + always keep audio climax impacts
    strong = [
        c for c in candidates
        if c.get("entertaining")
        or _is_climax(c)
        or coerce_virality_score(c.get("composite_score"), c.get("virality_score")) >= 48
        or "gpt_transcript" in (c.get("sources") or [])
    ]
    pool = strong or list(candidates)
    climaxes = [c for c in pool if _is_climax(c)]
    rest = [c for c in pool if not _is_climax(c)]
    rest = sorted(
        rest,
        key=lambda x: coerce_virality_score(x.get("composite_score"), x.get("virality_score"), x.get("score")),
        reverse=True,
    )
    climaxes = sorted(
        climaxes,
        key=lambda x: (
            float(x.get("z_score") or 0),
            coerce_virality_score(x.get("composite_score"), x.get("virality_score"), x.get("score")),
        ),
        reverse=True,
    )
    # Pin strongest climaxes at the front of the GPT pool
    pool = (climaxes[: max(4, target_count)] + rest)[: min(22, max(target_count * 3, 12))]
    compact = []
    for c in pool:
        compact.append({
            "time_sec": c.get("time_sec"),
            "vision_score": c.get("vision_score"),
            "virality_score": c.get("virality_score") or c.get("vision_score"),
            "composite_score": c.get("composite_score") or composite_virality_score(c),
            "summary": c.get("summary") or c.get("vision_summary") or "",
            "title": c.get("title") or "",
            "transcript_snip": (c.get("transcript_snip") or c.get("text") or "")[:320],
            "audio_kinds": c.get("kinds") or [],
            "sources": c.get("sources") or [],
            "climax": _is_climax(c),
            "audio_z": round(float(c.get("z_score") or 0), 2),
            "hook_score": c.get("hook_score"),
            "emotion_score": c.get("emotion_score"),
            "payoff_score": c.get("payoff_score"),
            "standalone_score": c.get("standalone_score"),
            "energy_score": c.get("energy_score"),
            "entertaining": c.get("entertaining"),
            "hook": c.get("hook") or "",
            "payoff": c.get("payoff") or "",
            "reaction": c.get("reaction") or "",
            "reason": c.get("reason") or "",
            "start_sec": c.get("start_sec"),
            "end_sec": c.get("end_sec"),
            "suggested_duration_sec": round(
                float(c.get("end_sec") or 0) - float(c.get("start_sec") or 0), 1
            )
            if c.get("start_sec") is not None and c.get("end_sec") is not None
            else None,
        })
    context_block = (
        f"Title: {video_title or 'unknown'}\n"
        f"Creator: {streamer_name or 'unknown'}\n"
        f"Duration: {video_duration_sec or 'unknown'}s\n"
        f"User context: {(video_context or '').strip() or 'infer from title + candidate text'}"
    )
    prompt = (
        "You rank short-form clip candidates from ONE long video.\n"
        "Pick moments with a complete arc: hook → payoff → reaction "
        "(industry clipper standard — not just the loudest second).\n\n"
        f"VIDEO CONTEXT\n{context_block}\n\n"
        f"Pick up to {target_count} DISTINCT clips. Prefer the true peak of the piece "
        "over random loud or talky bits.\n"
        "Use the five sub-scores (hook/emotion/payoff/standalone/energy) when present.\n"
        "CRITICAL: climax=true = strongest audio impact peaks "
        "(finish / knockout-level hit / crash / roar). When any exist, "
        "at least one top-ranked clip MUST be climax=true unless context rejects it.\n"
        "Prefer candidates where audio + motion agree, and where AFTER/reaction is clear.\n"
        f"LENGTH: {lo:.0f}–{hi:.0f}s (target ~{preferred:.0f}s). "
        "Start before the setup, end after the reaction — never cut the payoff short.\n"
        "SCORING spread: #1 ≈ 92–98 if it is the real climax, then drop fast. "
        "Ordinary filler stays under 55.\n"
        "Reject: intros, ads, setup without payoff, dead air, mid-sentence starts.\n"
        "caption = quote from transcript_snip when present; else a short stake line.\n"
        f"Candidates:\n{json.dumps(compact, ensure_ascii=False)}\n"
        "Return JSON only:\n"
        '{"clips":[{"time_sec":0,"start_sec":0,"end_sec":20,"score":0-100,'
        '"title":"","caption":"","reason":"why this is the peak","hook":""}]}'
    )
    try:
        client = _client()
        resp = client.chat.completions.create(
            model=_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You pick the true climactic / most shareable moments for whatever "
                        "this video is about. Use the provided context. Do not assume a genre. "
                        "Prefer fewer great clips. Wide score spread. JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        clips = data.get("clips") if isinstance(data, dict) else data
        if not isinstance(clips, list):
            raise ValueError("bad shape")
        by_near = pool
        out = []
        used: List[float] = []
        for c in clips:
            if not isinstance(c, dict):
                continue
            start = float(c.get("start_sec") or 0)
            end = float(c.get("end_sec") or 0)
            peak = float(c.get("time_sec") or ((start + end) / 2))
            if any(abs(peak - u) < 12 for u in used):
                continue
            start, end = clamp_window_to_target(
                start,
                end,
                duration_sec=float(video_duration_sec or end + 1),
                target_duration_sec=float(target_duration_sec),
                peak_sec=peak,
                prefer_story=True,
            )
            if end <= start + 2:
                continue
            base = next(
                (v for v in by_near if abs(float(v.get("time_sec") or 0) - peak) < 6),
                {},
            )
            gpt_score = coerce_virality_score(c.get("score"))
            comp = coerce_virality_score(
                base.get("composite_score"),
                base.get("virality_score"),
                base.get("vision_score"),
            )
            # Blend model taste with multi-signal composite
            score = (0.55 * gpt_score + 0.45 * comp) if comp > 0 else gpt_score
            base_climax = bool(
                base.get("climax")
                or "audio_climax" in (base.get("sources") or [])
                or "climax_impact" in (base.get("kinds") or [])
            )
            if not base.get("entertaining") and score < 70 and not base_climax:
                score *= 0.85
            if base_climax:
                score = max(score, 78.0)
            out.append({
                "time_sec": peak,
                "start_sec": start,
                "end_sec": end,
                "score": score,
                "composite_score": comp or score,
                "virality_score": score,
                "vision_score": base.get("vision_score"),
                "entertaining": base.get("entertaining"),
                "climax": base_climax,
                "z_score": base.get("z_score"),
                "sources": base.get("sources") or [],
                "kinds": base.get("kinds") or [],
                "transcript_snip": base.get("transcript_snip") or base.get("text") or "",
                "title": clean_caption_text(c.get("title") or base.get("title") or "") or "Highlight",
                "caption": clean_caption_text(
                    c.get("caption") or base.get("caption") or base.get("transcript_snip") or ""
                ),
                "reason": (c.get("reason") or "").strip(),
                "hook": (c.get("hook") or base.get("hook") or "").strip(),
            })
            used.append(peak)
        out.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
        if out:
            return amplify_virality_scores(out[:target_count])
    except Exception as e:
        logger.warning("[GTA] gpt rank failed, using heuristic: %s", e)

    ranked = sorted(
        pool,
        key=lambda x: coerce_virality_score(
            x.get("composite_score"),
            x.get("virality_score"),
            x.get("vision_score"),
            x.get("score"),
        ),
        reverse=True,
    )
    out = []
    used_centers: List[float] = []
    for c in ranked:
        center = float(c.get("time_sec") or 0)
        if any(abs(center - u) < max(10.0, preferred * 0.7) for u in used_centers):
            continue
        if (
            c.get("entertaining") is False
            and not _is_climax(c)
            and coerce_virality_score(c.get("composite_score"), c.get("virality_score")) < 50
        ):
            continue
        start = float(c.get("start_sec") if c.get("start_sec") is not None else max(0, center - preferred * 0.35))
        end = float(
            c.get("end_sec")
            if c.get("end_sec") is not None
            else start + preferred
        )
        start, end = snap_window_to_transcript(
            start,
            end,
            [],
            duration_sec=float(video_duration_sec or end + 1),
            target_duration_sec=float(target_duration_sec),
            peak_sec=center,
        )
        used_centers.append(center)
        caption = clean_caption_text(
            c.get("caption") or c.get("transcript_snip") or c.get("text") or c.get("summary") or ""
        )
        score = coerce_virality_score(
            c.get("composite_score"),
            c.get("virality_score"),
            c.get("vision_score"),
            c.get("score"),
        )
        out.append({
            "time_sec": center,
            "start_sec": start,
            "end_sec": end,
            "score": score,
            "composite_score": score,
            "virality_score": score,
            "vision_score": c.get("vision_score"),
            "entertaining": c.get("entertaining"),
            "sources": c.get("sources") or [],
            "kinds": c.get("kinds") or [],
            "transcript_snip": c.get("transcript_snip") or c.get("text") or "",
            "title": clean_caption_text(c.get("title") or "") or "Highlight",
            "caption": caption,
            "reason": (c.get("reason") or "multi-signal virality rank").strip(),
            "hook": (c.get("hook") or "").strip(),
        })
        if len(out) >= target_count:
            break
    return amplify_virality_scores(out)


def captions_for_window(
    segments: List[Dict[str, Any]],
    *,
    start: float,
    end: float,
    fallback_texts: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Timed caption segments for a clip window — real speech only."""
    caps: List[Dict[str, Any]] = []
    for s in segments or []:
        text = clean_caption_text(s.get("text") or "")
        if not text:
            continue
        s0 = float(s.get("start") or 0)
        s1 = float(s.get("end") or s0)
        if s1 < start - 0.15 or s0 > end + 0.15:
            continue
        caps.append({"start": s0, "end": s1, "text": text})
    if caps:
        return caps
    for raw in fallback_texts or []:
        text = clean_caption_text(raw)
        if not text:
            continue
        from app.studio.video_engine.caption_burn import segments_from_fallback_text

        synth = segments_from_fallback_text(text, duration_sec=max(1.0, end - start))
        return [
            {
                "start": start + float(s["start"]),
                "end": start + float(s["end"]),
                "text": clean_caption_text(s["text"]),
            }
            for s in synth
            if clean_caption_text(s.get("text") or "")
        ]
    return []
