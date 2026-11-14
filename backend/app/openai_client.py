"""OpenAI client for GTAClipper."""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_openai_client():
    """
    Build a stable OpenAI client.

    openai==1.54.x passes `proxies=` into httpx.Client, which httpx>=0.28 rejects.
    Cursor also injects HTTP(S)_PROXY into agent-launched shells; those proxies often
    break API calls. We use an explicit httpx client with trust_env=False.
    """
    from openai import OpenAI
    import httpx

    key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in .env")

    timeout = httpx.Timeout(120.0, connect=30.0)
    http_client = httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,  # ignore broken Cursor/agent proxy env
    )
    return OpenAI(api_key=key, http_client=http_client)
