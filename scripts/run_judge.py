#!/usr/bin/env python3
"""
llm-judge: Orchestrate Claude Code judge agents to evaluate artifacts.
Supports: elo, gate, review modes with Swiss Elo tournament.

Usage:
    llm-judge <mode> [options] -- <artifact> [<artifact> ...]
"""

import argparse
import hashlib
import json
import subprocess
import os
import re
import shutil
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Default generic criteria
# ---------------------------------------------------------------------------

DEFAULT_CRITERIA = {
    "dimensions": [
        {"name": "Correctness",     "weight": 0.30, "desc": "Does it do what it claims? No factual or logical errors?"},
        {"name": "Completeness",    "weight": 0.25, "desc": "All parts of the task addressed? Edge cases handled?"},
        {"name": "Clarity",         "weight": 0.20, "desc": "Intent obvious? Structure logical? No ambiguous terms?"},
        {"name": "Maintainability", "weight": 0.15, "desc": "Well-organized? No unnecessary complexity?"},
        {"name": "EdgeCases",       "weight": 0.10, "desc": "Failure modes addressed? Errors handled gracefully?"},
    ],
}

DEFAULT_SYSTEM = (
    "You are an expert judge. Be rigorous and fair. When in doubt, rate down. "
    "Respond with JSON for pairwise comparisons, Markdown for critique/review."
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_criteria(criteria: dict) -> None:
    total = sum(d["weight"] for d in criteria["dimensions"])
    if abs(total - 1.0) > 0.001:
        raise ValueError(
            f"Criteria dimensions must sum to 1.0, got {total}. "
            f"Check: {[d['name'] for d in criteria['dimensions']]}"
        )

# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------

def load_artifact(raw: str) -> dict:
    if raw.startswith("inline:"):
        content = raw[7:]
    elif raw.startswith("http://") or raw.startswith("https://"):
        try:
            import urllib.request
            from urllib.parse import urlparse
            with urllib.request.urlopen(raw, timeout=30) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            parsed = urlparse(raw)
            aid = Path(parsed.path).name or parsed.netloc
            return {"id": aid, "content": content,
                    "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16]}
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
            aid = f"artifact_{id(raw)}"

    return {
        "id": aid,
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
    }


def load_artifacts(raws: list[str]) -> list[dict]:
    return [load_artifact(r) for r in raws]

# ---------------------------------------------------------------------------
# Claude Code invocation
# ---------------------------------------------------------------------------

def call_claude(prompt: str, model: str = "claude-sonnet-4-6",
                effort: str = "high", system: str = DEFAULT_SYSTEM,
                provider: str = "cli") -> str:
    """
    provider "cli"   → use `claude` CLI (local). model is the CLI model name.
    provider "minimax" → use minimax API (OpenAI-compatible). model is the API model name.
    provider "<URL>"  → use arbitrary OpenAI-compatible API base URL.
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
    import urllib.request
    base_url = _provider_base_url(provider)
    api_key = _provider_api_key(provider)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
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


def _provider_base_url(provider: str) -> str:
    if provider == "minimax":
        return "https://api.minimax.io/v1"
    if provider == "openai":
        return "https://api.openai.com/v1"
    return provider  # raw URL


def _provider_api_key(provider: str) -> str:
    """Look up API key from environment or pass store."""
    if provider == "minimax":
        # Key is stored in pass under minimax/api-key
        try:
            import subprocess
            return subprocess.check_output(
                ["pass", "show", "minimax/api-key"], text=True
            ).strip()
        except Exception:
            pass
        # Also check MINIMAX_API_KEY env var
        return os.environ.get("MINIMAX_API_KEY", os.environ.get("OPENAI_API_KEY", ""))

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_dimensions_text(dimensions: list[dict]) -> str:
    return "\n".join(
        f"- **{d['name']}** (weight {d['weight']:.0%}): {d['desc']}"
        for d in dimensions
    )


def build_pairwise_prompt(a: dict, b: dict, dimensions: list[dict], task: str) -> str:
    dims = build_dimensions_text(dimensions)
    return f"""You are an expert judge. Two artifacts are evaluated for this task:
"{task}"

Rate each artifact 1–5 on these dimensions, compute weighted scores, and pick the winner.

Dimensions:
{dims}

---
ARTIFACT A [{a['id']}]:
{a['content']}
---
ARTIFACT B [{b['id']}]:
{b['content']}
---

Respond ONLY with this JSON (no extra text):
{{"a_score": N.N, "b_score": N.N, "winner": "A" or "B", "reason": "..."}}"""


def build_critique_prompt(artifact: dict, dimensions: list[dict], task: str) -> str:
    dims = build_dimensions_text(dimensions)
    bar = "\n".join(
        f"- {k}/5: {v}" for k, v in {
            "5": "Exceptional — gold standard",
            "4": "Good — meets bar, minor polish",
            "3": "Acceptable — minor revision needed",
            "2": "Below bar — significant issues",
            "1": "Poor — do not use",
        }.items()
    )
    return f"""Critique this artifact. Score each dimension 1–5, compute weighted average, give actionable feedback.

Task: {task}

Dimensions:
{dims}

Quality bar:
{bar}

Artifact content:
{artifact['content']}

Respond in Markdown with:
## Dimension Scores
| Dimension | Score |
|-----------|-------|
...

## Overall: X.XX / 5.0
## Verdict: [Acceptable / Needs revision / Poor]
## Specific Feedback
- What to fix
- What to keep"""


def build_gate_prompt(artifact: dict, dimensions: list[dict], task: str) -> str:
    dims = build_dimensions_text(dimensions)
    return f"""Evaluate this artifact against pass/fail gates.

Task: {task}

Required dimensions:
{dims}

Artifact content:
{artifact['content']}

Respond with JSON:
{{"scores": {{"DimensionName": N, ...}}, "weighted": X.XX, "passed": true/false, "verdict": "one sentence"}}"""


# ---------------------------------------------------------------------------
# Result parsers
def _strip_code_fence(text: str) -> str:
    """Strip leading/trailing ```json ... ``` or ``` ... ``` fences."""
    text = text.strip()
    # Handle ```json ... ``` (with optional language tag)
    for fence in ("```json", "```JSON", "```json\n", "```JSON\n"):
        if text.startswith(fence):
            end = text.rfind("```")
            if end != -1:
                return text[len(fence):end].strip()
    # Handle bare ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        # Find last line that is exactly ```
        last_fence = len(lines) - 1 - next((i for i in range(len(lines)-1, -1, -1) if lines[i].strip() == "```"), -1)
        if last_fence > 0:
            return "\n".join(lines[1:last_fence]).strip()
    return text


def parse_pairwise_result(raw: str) -> dict:
    # Strip MiniMax thinking blocks before JSON parsing
    # MiniMax emits:  Think: ...  or  <> blocks
    text = re.sub(r"<[^>]*>[^<]*</[^>]*>", "", raw, flags=re.IGNORECASE | re.DOTALL)
    cleaned = _strip_code_fence(text)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract winner from markdown critique text
        # Pattern: "Winner: A" or "## Winner: A" or "**Winner: A**"
        winner_match = re.search(r"(?:^|\n)##?\s*Winner:\s*([AB])", cleaned, re.M)
        score_a, score_b = 3.0, 3.0
        winner = "A"
        if winner_match:
            winner = winner_match.group(1)
        # Try to extract confidence/quality scores
        conf_a = re.search(r"A.*?(\d+(?:\.\d+)?)\s*(?:/|out of|/)", cleaned[:500], re.I)
        conf_b = re.search(r"B.*?(\d+(?:\.\d+)?)\s*(?:/|out of|/)", cleaned[:500], re.I)
        if conf_a:
            score_a = min(5.0, max(1.0, float(conf_a.group(1))))
        if conf_b:
            score_b = min(5.0, max(1.0, float(conf_b.group(1))))
        return {
            "a_score": score_a,
            "b_score": score_b,
            "winner": winner,
            "reason": cleaned[:200],
        }
    raise ValueError(f"Could not parse pairwise result: {cleaned[:300]}")

def parse_gate_result(raw: str) -> dict:
    try:
        data = json.loads(_strip_code_fence(raw))
        weighted = float(data.get("weighted", 0.0))
        # Clamp weighted to valid range (model may compute wrong)
        weighted = max(1.0, min(5.0, weighted))
        return {
            "scores": data.get("scores", {}),
            "score": weighted,
            "passed": data.get("passed", False),
            "verdict": data.get("verdict", ""),
        }
    except Exception:
        return {"scores": {}, "score": 0.0, "passed": False, "verdict": f"[parse error] {raw[:100]}"}


# ---------------------------------------------------------------------------
# Mode: review (critique)
# ---------------------------------------------------------------------------

def mode_review(artifacts: list[dict], criteria: dict, task: str,
                output: Optional[str], model: str, effort: str, provider: str) -> str:
    dims = criteria["dimensions"]
    lines = [f"# Review — {len(artifacts)} artifact(s)\n", f"**Task:** {task}\n"]

    for a in artifacts:
        prompt = build_critique_prompt(a, dims, task)
        result = call_claude(prompt, model=model, effort=effort, provider=provider)
        lines.append(f"\n## {a['id']}\n{result}")

    text = "\n".join(lines)
    if output:
        Path(output).write_text(text)
    print(text)
    return text


# ---------------------------------------------------------------------------
# Mode: gate (pass/fail)
# ---------------------------------------------------------------------------

def mode_gate(artifacts: list[dict], criteria: dict, task: str,
              output: Optional[str], model: str, effort: str, provider: str) -> str:
    dims = criteria["dimensions"]
    results = []
    for a in artifacts:
        prompt = build_gate_prompt(a, dims, task)
        raw = call_claude(prompt, model=model, effort=effort, provider=provider)
        results.append({"id": a["id"], **parse_gate_result(raw)})

    all_passed = all(r["passed"] for r in results)
    lines = [f"# Gate Results\n", f"**Task:** {task}\n"]
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        lines.append(f"{icon} **{r['id']}** — {r['score']:.2f}/5 — {r['verdict']}")
    lines.append(f"\n**Overall: {'PASS ✅' if all_passed else 'FAIL ❌'}**")

    text = "\n".join(lines)
    if output:
        Path(output).write_text(text)
    print(text)
    return text


# ---------------------------------------------------------------------------
# Mode: elo (Swiss ranking)
# ---------------------------------------------------------------------------

def mode_elo(
    artifacts: list[dict],
    criteria: dict,
    task: str,
    elo_mode: str,
    elo_K: int,
    n_rounds: int,
    output: Optional[str],
    model: str,
    effort: str,
    provider: str,
) -> str:
    # references/ is a sibling to scripts/ — add parent dir to path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "references"))
    from elo import FIFOCache, rank_swiss_elo

    n = len(artifacts)
    dims_text = build_dimensions_text(criteria["dimensions"])
    dims_hash = hashlib.sha256(dims_text.encode()).hexdigest()[:8]
    cache = FIFOCache()

    artifact_map: dict[str, dict] = {a["id"]: a for a in artifacts}

    def compare_fn(task: str, dims_hash: str,
                   a_elo, b_elo, cache: FIFOCache) -> dict:
        a = artifact_map[a_elo.id]
        b = artifact_map[b_elo.id]

        cached = cache.get(task, dims_hash, a_elo.id, a_elo.content_hash,
                           b_elo.id, b_elo.content_hash)
        if cached:
            return cached

        prompt = build_pairwise_prompt(a, b, criteria["dimensions"], task)
        raw = call_claude(prompt, model=model, effort=effort, provider=provider)
        result = parse_pairwise_result(raw)

        normalized = {
            "a_score": max(1.0, min(5.0, float(result.get("a_score", 3.0)))),
            "b_score": max(1.0, min(5.0, float(result.get("b_score", 3.0)))),
            "winner": result.get("winner", "A") if result.get("winner") in ("A", "B") else "A",
            "reason": result.get("reason", ""),
        }
        cache.set(task, dims_hash, a_elo.id, a_elo.content_hash,
                  b_elo.id, b_elo.content_hash, normalized)
        return normalized

    result = rank_swiss_elo(
        artifacts=artifacts,
        task=task,
        dims_hash=dims_hash,
        cache=cache,
        compare_fn=compare_fn,
        n_rounds=n_rounds,
        elo_mode=elo_mode,
        elo_K=elo_K,
    )

    ranked_ids = result["ranked"]
    elo_map = result["artifacts"]
    rounds_log = result["rounds_log"]
    cache_stats = cache.stats()

    # Header — show narrowing info
    narrowing_info = ""
    if elo_mode == "rank":
        narrowing_info = f" (sorted top-{elo_K}, R3 competes 1..{min(n, elo_K+2)})"
    elif elo_mode == "class":
        narrowing_info = f" (class {elo_K}, R3 competes {max(1,elo_K-2)}..{min(n, elo_K+2)})"

    lines = [
        f"# Elo Ranking — {len(ranked_ids)} of {n}{narrowing_info}\n",
        f"**Task:** {task}\n",
        f"**Provider:** {provider} / {model} ({effort} effort)\n",
        f"**Rounds:** {n_rounds}\n",
        f"**Cache:** {cache_stats['cached']} entries stored\n",
    ]

    # Final ranking table
    lines.append(f"\n## Final Ranking\n")
    lines.append("| Rank | Artifact | Elo | Matches |")
    lines.append("|------|----------|-----|---------|")
    for i, aid in enumerate(ranked_ids):
        e = elo_map[aid]
        lines.append(f"| {i+1} | {aid} | {e['elo']} | {e['n']} |")

    # Rounds log
    lines.append(f"\n## Rounds\n")
    for rec in rounds_log:
        rnd = rec["round"]
        lines.append(f"\n**Round {rnd}**")
        if rec["byes"]:
            lines.append(f"  Byes: {', '.join(rec['byes'])}")
        for p in rec["pairs"]:
            w = p["winner"]
            w_label = p["a"] if w == "A" else p["b"]
            lines.append(
                f"  {p['a']} ({p['a_elo_after']}) vs {p['b']} ({p['b_elo_after']}) "
                f"→ **{w_label}** · {p['reason'][:70]}"
            )

    text = "\n".join(lines)
    if output:
        Path(output).write_text(text)
    print(text)
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_rank_range(s: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse rank spec:
      None       → no limit (return all)
      "3"        → top 3
      "1..3"     → ranks 1 through 3
    Returns (rank_lo, rank_hi) 1-indexed inclusive, or (None, None).
    """
    if s is None:
        return (None, None)
    if ".." in s:
        parts = s.split("..")
        lo, hi = int(parts[0]), int(parts[1])
        return (lo, hi)
    if "-" in s:
        parts = s.split("-")
        lo, hi = int(parts[0]), int(parts[1])
        return (lo, hi)
    v = int(s)
    return (v, v)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Opus Judge — Swiss Elo artifact evaluation via Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
NOTE: Artifacts must come BEFORE --prompt. argparse quirk.

Modes:
  review  Detailed qualitative critique (Markdown, one Opus call per artifact)
  gate    Pass/fail assessment per artifact (one Opus call per artifact)
  elo     Swiss Elo tournament — rank top-K or full ranking (3 rounds, pairwise)

Examples:
  llm-judge review ./memo.md ./notes.md --prompt "Which is clearer?"
  llm-judge gate ./proposal.md --prompt "Does this pass safety gates?"
  llm-judge elo ./a.go ./b.go ./c.go ./d.go --prompt "Most idiomatic Go?"
  llm-judge elo --elo-rank 3 ./*.md --prompt "Find the top 3 essays"
  llm-judge elo --elo-class 5 ./*.md --prompt "Rank the middle tier"
        """,
    )
    parser.add_argument("mode", choices=["review", "gate", "elo"])
    parser.add_argument("artifacts", nargs="*", help="File paths, URLs, or inline:TEXT (put before --prompt)")
    parser.add_argument("--prompt", "-t", required=True,
        help="Task — what 'good' means. REQUIRED. Must come AFTER artifacts.")
    parser.add_argument("--model", default="claude-sonnet-4-6",
        help="Model name. For CLI provider, use CLI model name (e.g. claude-sonnet-4-6). "
             "For API providers (minimax/openai), use the provider's model ID.")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--provider", default="cli",
        help="Provider: 'cli' (claude CLI, default), 'minimax' (API), or full URL for OpenAI-compatible API. "
             "Because Elo comparisons are anchored pairwise judgments, weaker models can discriminate accurately.")
    parser.add_argument("--criteria", type=Path,
        help="Path to criteria JSON file")
    parser.add_argument("--criteria-text",
        help="Inline criteria as JSON string")
    parser.add_argument("--rank", help="[DEPRECATED] Use --elo-rank or --elo-class instead")
    parser.add_argument("--elo-rank",
        help="Elo mode: sort-and-return top K (knockout threshold). 'all' for full ranking. E.g. --elo-rank 5 returns top 6 (even K rounds up).")
    parser.add_argument("--elo-class",
        help="Elo mode: roughly-sorted class K band. Band = ranks max(1,K-2) .. min(N, K+2). E.g. --elo-class 5 returns ranks 3-7.")
    parser.add_argument("--rounds", type=int, default=3,
        help="Number of Swiss rounds (elo mode). Default: 3")
    parser.add_argument("--output", "-o", type=Path)

    args = parser.parse_args()

    # Load criteria
    if args.criteria:
        criteria = json.loads(args.criteria.read_text())
    elif args.criteria_text:
        criteria = json.loads(args.criteria_text)
    else:
        criteria = DEFAULT_CRITERIA
    validate_criteria(criteria)

    # Load artifacts
    if not args.artifacts:
        parser.error("At least one artifact required")
    artifacts = load_artifacts(args.artifacts)
    n = len(artifacts)

    output = str(args.output) if args.output else None

    if args.mode == "review":
        mode_review(artifacts, criteria, args.prompt, output, args.model, args.effort, args.provider)

    elif args.mode == "gate":
        mode_gate(artifacts, criteria, args.prompt, output, args.model, args.effort, args.provider)

    elif args.mode == "elo":
        elo_mode = "all"
        elo_K = 0
        if args.elo_rank is not None:
            if args.elo_rank.lower() == "all":
                elo_mode = "all"
                elo_K = 0
            else:
                elo_mode = "rank"
                elo_K = int(args.elo_rank)
        elif args.elo_class is not None:
            elo_mode = "class"
            elo_K = int(args.elo_class)
        elif args.rank:
            # DEPRECATED fallback
            rank_lo, rank_hi = parse_rank_range(args.rank)
            if rank_lo == rank_hi:
                elo_mode = "rank"
                elo_K = rank_lo
            else:
                elo_mode = "class"
                elo_K = rank_hi

        mode_elo(
            artifacts, criteria, args.prompt,
            elo_mode=elo_mode,
            elo_K=elo_K,
            n_rounds=args.rounds,
            output=output,
            model=args.model,
            effort=args.effort,
            provider=args.provider,
        )


if __name__ == "__main__":
    main()
