"""Artifact loading for llm-judge: files, inline text, and URLs."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def load_artifact(raw: str) -> dict:
    """Load a single artifact from a file path, inline text, or URL.

    Returns dict with:
      - id: display name (filename, URL host, or auto-generated)
      - content: full text of the artifact
      - content_hash: sha256 hexdigest[:16] for caching
    """
    if raw.startswith("inline:"):
        content = raw[7:]
        aid = f"artifact_{hashlib.sha256(content.encode()).hexdigest()[:8]}"
    elif raw.startswith("http://") or raw.startswith("https://"):
        try:
            with urllib.request.urlopen(raw, timeout=30) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            parsed = urlparse(raw)
            aid = Path(parsed.path).name or parsed.netloc
        except Exception as e:
            content = f"[Could not fetch {raw}: {e}]"
            aid = raw
    else:
        path = Path(raw)
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            aid = path.name
        else:
            content = raw
            aid = f"artifact_{hashlib.sha256(raw.encode()).hexdigest()[:8]}"

    return {
        "id": aid,
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
    }


def load_artifacts(raws: list[str]) -> list[dict]:
    """Load multiple artifacts."""
    return [load_artifact(r) for r in raws]
