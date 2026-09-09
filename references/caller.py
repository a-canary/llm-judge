"""LLM invocation for llm-judge: claude CLI and OpenAI-compatible HTTP API."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request

from references.providers import resolve_api_url as _resolve_api_url, get_api_key as _get_api_key


DEFAULT_SYSTEM = (
    "You are an expert judge. Be rigorous and fair. When in doubt, rate down. "
    "Respond with JSON for pairwise comparisons, Markdown for critique/review."
)


def call_claude(prompt: str, model: str = "claude-sonnet-4-6",
                effort: str = "high", system: str = DEFAULT_SYSTEM,
                provider: str = "cli") -> str:
    """
    Invoke an LLM with the given prompt.

    provider "cli"    → use `claude` CLI (local). model is the CLI model name.
    provider "<URL>"  → use arbitrary OpenAI-compatible API base URL. model is the API model name.

    Returns the raw text response.
    """
    if provider == "cli":
        if not shutil.which("claude"):
            raise RuntimeError(
                "claude not found in PATH. Install Claude Code: "
                "https://docs.anthropic.com/claude-code"
            )
        proc = subprocess.run(
            ["claude", "--print", "--model", model, "--effort", effort,
             f"--system-prompt={system}"],
            input=prompt, capture_output=True, text=True, timeout=300,
            env={**os.environ, "CLAUDE_NO_TIP": "1"},
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr}")
        return proc.stdout.strip()

    # API mode: OpenAI-compatible
    base_url = _resolve_api_url(provider)
    api_key = _get_api_key(base_url)
    if not api_key:
        raise RuntimeError(
            f"No API key found for '{base_url}'. "
            "Set LLM_JUDGE_API_KEY env var, or use keyring "
            "(python -m keyring set llm-judge <host>://api_key <key>). "
            "Run: python -m keyring set llm-judge https://api.minimax.io/v1://api_key YOUR_KEY"
        )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()
