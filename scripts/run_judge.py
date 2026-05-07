#!/usr/bin/env python3
"""
llm-judge: Orchestrate LLM judge agents to evaluate artifacts.
Supports: elo, gate, review modes with Swiss Elo tournament.

Usage:
    llm-judge <mode> [options] -- <artifact> [<artifact> ...]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------
# Credential lookup — cross-platform, pipeline-friendly
# --------------------------------------------------------------------------

def _resolve_api_url(provider_arg: str) -> str:
    """Resolve the API base URL.

    Priority:
    1. LLM_JUDGE_API_BASE env var (pipeline-friendly, always wins)
    2. provider_arg if it looks like a URL
    """
    if provider_arg == "cli":
        return "cli"
    env_base = os.environ.get("LLM_JUDGE_API_BASE", "").strip()
    if env_base:
        return env_base
    if "://" in provider_arg:
        return provider_arg
    return ""


def _get_api_key(base_url: str) -> str:
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
        aid = f"artifact_{hashlib.sha256(content.encode()).hexdigest()[:8]}"
    elif raw.startswith("http://") or raw.startswith("https://"):
        try:
            import urllib.request
            from urllib.parse import urlparse
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
    return [load_artifact(r) for r in raws]

# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------

def call_claude(prompt: str, model: str = "claude-sonnet-4-6",
                effort: str = "high", system: str = DEFAULT_SYSTEM,
                provider: str = "cli") -> str:
    """
    provider "cli"    → use `claude` CLI (local). model is the CLI model name.
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
    import urllib.request
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

Rate each artifact 1-5 on these dimensions, compute weighted scores, and pick the winner.

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
    return f"""Critique this artifact. Score each dimension 1-5, compute weighted average, give actionable feedback.

Task: {task}

Dimensions:
{dims}

---
ARTIFACT:
{artifact['content']}
---

Score each dimension and respond ONLY with this JSON (no extra text):
{{"scores": {{"<dim>": N, ...}}, "average": N.N, "verdict": "...", "feedback": "..."}}"""


def build_gate_prompt(artifact: dict, dimensions: list[dict], task: str) -> str:
    dims = build_dimensions_text(dimensions)
    return f"""Does this artifact meet the bar for this task?
"{task}"

Score 1-5 on each dimension, compute weighted average. Respond ONLY with this JSON (no extra text):
{{"score": N.N, "passed": true|false, "verdict": "..."}}

Dimensions:
{dims}

---
ARTIFACT:
{artifact['content']}
---"""

# ---------------------------------------------------------------------------
# Result parsers
# ---------------------------------------------------------------------------

def parse_pairwise_result(raw: str) -> dict:
    try:
        # Try JSON first
        data = json.loads(raw)
        return {
            "a_score": float(data["a_score"]),
            "b_score": float(data["b_score"]),
            "winner": data["winner"].upper(),
            "reason": data.get("reason", ""),
        }
    except Exception:
        pass
    # Fallback: regex
    winner = None
    for w in ("A", "B"):
        if re.search(rf'\bWinner:\s*{w}\b', raw, re.IGNORECASE):
            winner = w
            break
    scores = [float(s) for s in re.findall(r'Score[_ ]?[AB]?:\s*(\d+\.?\d*)', raw, re.IGNORECASE)]
    a_score = scores[0] if len(scores) > 0 else 5.0
    b_score = scores[1] if len(scores) > 1 else 5.0
    winner = winner or ("A" if a_score > b_score else "B" if b_score > a_score else "A")
    return {"a_score": a_score, "b_score": b_score, "winner": winner, "reason": raw[:200]}


def parse_gate_result(raw: str) -> dict:
    try:
        data = json.loads(raw)
        return {
            "score": float(data["score"]),
            "passed": bool(data.get("passed", float(data["score"]) >= 3.5)),
            "verdict": data.get("verdict", ""),
        }
    except Exception:
        score_match = re.search(r'Score:\s*(\d+\.?\d*)', raw, re.IGNORECASE)
        score = float(score_match.group(1)) if score_match else 3.0
        passed = "pass" in raw.lower() or score >= 3.5
        verdict = raw[:200]
        return {"score": score, "passed": passed, "verdict": verdict}

# ---------------------------------------------------------------------------
# Mode: review
# ---------------------------------------------------------------------------

def mode_review(artifacts: list[dict], criteria: dict, task: str,
                output: Optional[str], model: str, effort: str, provider: str) -> str:
    dims = criteria["dimensions"]
    lines = [f"# Review — {len(artifacts)} artifacts\n", f"**Task:** {task}\n"]
    for a in artifacts:
        prompt = build_critique_prompt(a, dims, task)
        raw = call_claude(prompt, model=model, effort=effort, provider=provider)
        try:
            data = json.loads(raw)
            scores = data.get("scores", {})
            feedback = data.get("feedback", "")
            avg = data.get("average", 0)
            lines.append(f"\n## {a['id']} — {avg:.2f}/5")
            for d in dims:
                s = scores.get(d["name"], "?")
                lines.append(f"- **{d['name']}**: {s}/5")
            lines.append(f"\n{feedback}\n")
        except Exception:
            lines.append(f"\n## {a['id']}\n\n{raw[:500]}\n")
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
# Mode: elo
# ---------------------------------------------------------------------------

def mode_elo(artifacts: list[dict], criteria: dict, task: str,
             output: Optional[str], model: str, effort: str, provider: str,
             elo_mode: str, elo_K: int, n_rounds: int) -> str:

    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "references"))
    from elo import FIFOCache, rank_swiss_elo

    n = len(artifacts)
    dims_text = build_dimensions_text(criteria["dimensions"])
    dims_hash = hashlib.sha256(dims_text.encode()).hexdigest()[:12]
    cache = FIFOCache()

    def compare_fn(a_id: str, a_elo: float, a_content: str,
                   b_id: str, b_elo: float, b_content: str) -> dict:
        a_hash = hashlib.sha256(a_content.encode()).hexdigest()[:8]
        b_hash = hashlib.sha256(b_content.encode()).hexdigest()[:8]
        cached = cache.get(task, dims_hash, a_id, a_hash, b_id, b_hash)
        if cached:
            return cached
        prompt = build_pairwise_prompt(
            {"id": a_id, "content": a_content},
            {"id": b_id, "content": b_content},
            criteria["dimensions"], task
        )
        raw = call_claude(prompt, model=model, effort=effort, provider=provider)
        result = parse_pairwise_result(raw)
        winner_key = result["winner"]
        normalized = {"a_wins": 1.0 if winner_key == "A" else 0.0,
                      "b_wins": 1.0 if winner_key == "B" else 0.0,
                      "draw": 1.0 if winner_key not in ("A", "B") else 0.0,
                      "a_score": result["a_score"],
                      "b_score": result["b_score"],
                      "reason": result["reason"]}
        cache.set(task, dims_hash, a_id, a_hash, b_id, b_hash, normalized)
        return normalized

    result = rank_swiss_elo(
        artifacts=artifacts,
        task=task,
        dims_hash=dims_hash,
        compare_fn=compare_fn,
        cache=cache,
        n_rounds=n_rounds,
        elo_mode=elo_mode,
        elo_K=elo_K,
    )
    ranked_ids = result["ranked_ids"]
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
        f"**Cache:** {cache_stats['cached']} hits\n",
        "\n## Final Ranking\n",
        "| Rank | Artifact       | Elo    | Matches |",
        "|------|----------------|--------|---------|",
    ]
    for rank, ae in enumerate(result["ranked"], 1):
        lines.append(f"| {rank}    | {ae.id:<15} | {ae.elo:6.1f} | {len(ae.matches):7} |")

    if rounds_log:
        lines.append("\n## Rounds Log")
        for rlog in rounds_log:
            lines.append(f"\n### Round {rlog['round']} — {len(rlog['matches'])} matches")
            for m in rlog["matches"]:
                lines.append(f"- ({m['a_id']} {m['a_elo']:.0f}) vs ({m['b_id']} {m['b_elo']:.0f}) → {m['winner']} | {m['reason'][:80]}")

    text = "\n".join(lines)
    if output:
        Path(output).write_text(text)
    print(text)
    return text

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="llm-judge: evaluate artifacts with an LLM judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  llm-judge review ./memo.md ./notes.md --prompt "Clear technical writing?"
  llm-judge gate ./proposal.md --prompt "Does this pass safety gates?"
  llm-judge elo ./a.go ./b.go ./c.go ./d.go --prompt "Most idiomatic Go?"
  llm-judge elo --elo-rank 3 ./*.md --prompt "Find the top 3 essays"
  llm-judge elo --elo-class 4 ./*.md --prompt "Select top 4 without full sort"
        """,
    )
    parser.add_argument("mode", choices=["review", "gate", "elo"])
    parser.add_argument("artifacts", nargs="*", help="File paths, URLs, or inline:TEXT (put before --prompt)")
    parser.add_argument("--prompt", help="Task framing what good means (required)")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Model name [default: claude-sonnet-4-6]")
    parser.add_argument("--provider", default="cli",
                        help="Provider: cli, minimax, openai, or URL [default: cli]")
    parser.add_argument("--effort", default="high",
                        help="Claude effort: low, medium, high [default: high]")
    parser.add_argument("--criteria", type=Path, help="Path to criteria JSON file")
    parser.add_argument("--criteria-text", help="Inline criteria as JSON string")
    parser.add_argument("--elo-rank", type=int,
                        help="Elo mode: sorted top-K. R3 competes ranks 1..K+2. Best for EA top-K selection.")
    parser.add_argument("--elo-class", type=int,
                        help="Elo mode: pivot top-K. R3 competes ranks K-2..K+2, returns top K unsorted. Best for EA survivor selection without full sort.")
    parser.add_argument("--rounds", type=int, default=3, help="Elo rounds [default: 3]")
    parser.add_argument("--output", help="Write output to file [default: stdout]")
    args = parser.parse_args()

    if not args.artifacts:
        parser.print_help()
        return

    # Resolve criteria
    if args.criteria_text:
        criteria = json.loads(args.criteria_text)
    elif args.criteria:
        criteria = json.loads(args.criteria.read_text())
    else:
        criteria = DEFAULT_CRITERIA
    validate_criteria(criteria)

    # Determine task
    task = args.prompt or "Which artifact is better? Rate overall quality."

    # Determine Elo narrowing
    elo_mode = "all"
    elo_K = 0
    if args.elo_rank is not None:
        elo_mode = "rank"
        elo_K = args.elo_rank
    elif args.elo_class is not None:
        elo_mode = "class"
        elo_K = args.elo_class

    # Load artifacts
    artifacts = load_artifacts(args.artifacts)

    # Dispatch
    if args.mode == "review":
        mode_review(artifacts, criteria, task, args.output, args.model, args.effort, args.provider)
    elif args.mode == "gate":
        mode_gate(artifacts, criteria, task, args.output, args.model, args.effort, args.provider)
    elif args.mode == "elo":
        mode_elo(artifacts, criteria, task, args.output, args.model, args.effort, args.provider,
                 elo_mode, elo_K, args.rounds)


if __name__ == "__main__":
    main()