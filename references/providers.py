#!/usr/bin/env python3
"""Cross-platform credential lookup for llm-judge providers."""

from __future__ import annotations

import os
import subprocess
from typing import Optional


def resolve_api_url(provider_arg: str) -> str:
    """Resolve the API base URL.

    Priority:
    1. LLM_JUDGE_API_BASE env var (pipeline-friendly, always wins)
    2. provider_arg if it looks like a URL
    3. "cli" if provider_arg is the literal string "cli"
    """
    if provider_arg == "cli":
        return "cli"
    env_base = os.environ.get("LLM_JUDGE_API_BASE", "").strip()
    if env_base:
        return env_base
    if "://" in provider_arg:
        return provider_arg
    return ""


def get_api_key(base_url: str) -> str:
    """Look up the API key for a given base URL.

    Priority:
    1. LLM_JUDGE_API_KEY env var  (pipeline-friendly, always wins)
    2. keyring: service="llm-judge", key="<host>://api_key"
    3. pass: "pass show <host>/api-key"  (Unix-only, last resort)
    """
    if base_url == "cli":
        return ""

    # Env var first
    api_key = os.environ.get("LLM_JUDGE_API_KEY", "").strip()
    if api_key:
        return api_key

    # Derive host from base_url for keyring/pass lookup
    host = base_url.split("://")[1].rstrip("/") if "://" in base_url else base_url

    # keyring: cross-platform system keychain
    try:
        import keyring
        stored = keyring.get_password("llm-judge", f"{host}://api_key")
        if stored:
            return stored
    except Exception:
        pass

    # pass: Unix-only last resort
    try:
        key = subprocess.check_output(["pass", "show", f"{host}/api-key"], text=True).strip()
        if key:
            return key
    except Exception:
        pass

    return ""
