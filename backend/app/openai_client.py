"""OpenAI client for GTAClipper."""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_openai_client():
    from openai import OpenAI

    key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in .env")
    return OpenAI(api_key=key)
