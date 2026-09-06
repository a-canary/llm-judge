"""Artifact loading for llm-judge: files, inline text, and URLs."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


class ArtifactLoadError(Exception):
    """An artifact could not be loaded, so there is nothing to judge.

    Raised rather than substituting placeholder content: a judge handed
    "[Could not fetch ...]" scores the error message as if it were the work, and
    the run reports a verdict on an artifact that was never read. The loader is
    the same trust boundary the parsers are -- neither may invent its input.
    """


def load_artifact(raw: str) -> dict:
    """Load a single artifact from a file path, inline text, or URL.

    Returns dict with:
      - id: display name (filename, URL host, or auto-generated)
      - content: full text of the artifact
      - content_hash: sha256 hexdigest[:16] for caching

    Raises ArtifactLoadError when a URL cannot be fetched.
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
            # Fail loudly. A fetch failure means we have no artifact -- scoring a
            # placeholder would report a verdict on something never read.
            raise ArtifactLoadError(f"could not fetch {raw}: {e}") from e
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
