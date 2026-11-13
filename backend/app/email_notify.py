"""Optional email notify via Resend."""
from __future__ import annotations

import os
from typing import Any, Dict


def email_video(
    *,
    to_email: str,
    video_url: str,
    video_name: str = "GTAClipper video",
    message: str = "",
    subject: str = "",
    actor_name: str = "",
) -> Dict[str, Any]:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not configured")
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        raise ValueError("Valid to_email required")
    import resend

    resend.api_key = api_key
    from_email = os.getenv("OPS_FROM_EMAIL") or os.getenv("FROM_EMAIL") or "onboarding@resend.dev"
    title = video_name or "GTAClipper video"
    subj = subject or f"Your video is ready — {title}"
    html = f"<p><strong>{title}</strong> is ready.</p><p><a href='{video_url}'>Open video</a></p>"
    if message:
        html += f"<p>{message}</p>"
    resend.Emails.send({
        "from": from_email,
        "to": [to_email],
        "subject": subj,
        "html": html,
    })
    return {"sent": True, "to": to_email}
