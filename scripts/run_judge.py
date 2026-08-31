#!/usr/bin/env python3
"""
llm-judge: Orchestrate LLM judge agents to evaluate artifacts.
Supports: elo, gate, review modes with Swiss Elo tournament.

Usage:
    llm-judge <mode> [options] -- <artifact> [<artifact> ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Enable package-style imports from project root
_SCRIPT_DIR = Path(__file__).parent.resolve()
_ROOT = _SCRIPT_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from references import elo as _elo
from references.artifacts import load_artifacts
from references.caller import call_claude
from references.criteria import DEFAULT_CRITERIA, validate_criteria
from references.parsers import parse_gate_result, parse_pairwise_result
from references.prompts import (
    build_critique_prompt,
    build_dimensions_text,
    build_gate_prompt,
    build_pairwise_prompt,
)


@dataclass
class JudgeOpts:
    """Call-shape options shared by every mode_* function (model/effort/provider/output)."""
    model: str = "claude-sonnet-4-6"
    effort: str = "high"
    provider: str = "cli"
    output: Optional[str] = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def render_and_emit(text: str, output: Optional[str]) -> str:
    """Write text to optional --output path, echo to stdout, return text.
    Shared epilogue across review / gate / elo mode functions."""
    if output:
        Path(output).write_text(text)
    print(text)
    return text


# ---------------------------------------------------------------------------
# Mode: review
# ---------------------------------------------------------------------------


def mode_review(artifacts: list[dict], criteria: dict, task: str, opts: JudgeOpts) -> str:
    dims = criteria["dimensions"]
    lines = [f"# Review \u2014 {len(artifacts)} artifacts\n", f"**Task:** {task}\n"]
    for a in artifacts:
        prompt = build_critique_prompt(a, dims, task)
        raw = call_claude(prompt, model=opts.model, effort=opts.effort, provider=opts.provider)
        try:
            data = json.loads(raw)
            scores = data.get("scores", {})
            feedback = data.get("feedback", "")
            avg = data.get("average", 0)
            lines.append(f"\n## {a['id']} \u2014 {avg:.2f}/5")
            for d in dims:
                s = scores.get(d["name"], "?")
                lines.append(f"- **{d['name']}**: {s}/5")
            lines.append(f"\n{feedback}\n")
        except Exception:
            lines.append(f"\n## {a['id']}\n\n{raw[:500]}\n")
    return render_and_emit("\n".join(lines), opts.output)


# ---------------------------------------------------------------------------
# Mode: gate (pass/fail)
# ---------------------------------------------------------------------------


def mode_gate(artifacts: list[dict], criteria: dict, task: str, opts: JudgeOpts) -> str:
    dims = criteria["dimensions"]
    results = []
    for a in artifacts:
        prompt = build_gate_prompt(a, dims, task)
        raw = call_claude(prompt, model=opts.model, effort=opts.effort, provider=opts.provider)
        results.append({"id": a["id"], **parse_gate_result(raw)})
    all_passed = all(r["passed"] for r in results)
    lines = [f"# Gate Results\n", f"**Task:** {task}\n"]
    for r in results:
        icon = "\u2705" if r["passed"] else "\u274c"
        lines.append(f"{icon} **{r['id']}** \u2014 {r['score']:.2f}/5 \u2014 {r['verdict']}")
    # py3.9 compat: a backslash escape may not appear inside an f-string expression
    overall = "PASS \u2705" if all_passed else "FAIL \u274c"
    lines.append(f"\n**Overall: {overall}**")
    return render_and_emit("\n".join(lines), opts.output)


# ---------------------------------------------------------------------------
# Mode: elo
# ---------------------------------------------------------------------------


def mode_elo(artifacts: list[dict], criteria: dict, task: str, opts: JudgeOpts,
             elo_mode: str, elo_K: int, n_rounds: int) -> str:
    n = len(artifacts)
    dims_text = build_dimensions_text(criteria["dimensions"])
    dims_hash = hashlib.sha256(dims_text.encode()).hexdigest()[:12]
    cache = _elo.FIFOCache()

    def compare_fn(
        task: str,
        dims_hash: str,
        a: _elo.ArtifactElo,
        b: _elo.ArtifactElo,
        cache: _elo.FIFOCache,
    ) -> dict:
        cached = cache.get(task, dims_hash, a.id, a.content_hash, b.id, b.content_hash)
        if cached:
            return cached
        prompt = build_pairwise_prompt(
            {"id": a.id, "content": a.content},
            {"id": b.id, "content": b.content},
            criteria["dimensions"],
            task,
        )
        raw = call_claude(prompt, model=opts.model, effort=opts.effort, provider=opts.provider)
        result = parse_pairwise_result(raw)
        winner_key = result["winner"]
        normalized = {
            "a_wins": 1.0 if winner_key == "A" else 0.0,
            "b_wins": 1.0 if winner_key == "B" else 0.0,
            "draw": 1.0 if winner_key not in ("A", "B") else 0.0,
            "a_score": result["a_score"],
            "b_score": result["b_score"],
            "reason": result["reason"],
        }
        cache.set(task, dims_hash, a.id, a.content_hash, b.id, b.content_hash, normalized)
        return normalized

    result = _elo.rank_swiss_elo(
        artifacts=artifacts,
        task=task,
        dims_hash=dims_hash,
        compare_fn=compare_fn,
        cache=cache,
        n_rounds=n_rounds,
        elo_mode=elo_mode,
        elo_K=elo_K,
    )
    ranked_ids = result["ranked"]
    rounds_log = result["rounds_log"]
    cache_stats = cache.stats()

    # Header — show narrowing info
    narrowing_info = ""
    if elo_mode == "rank":
        narrowing_info = f" (sorted top-{elo_K}, R3 competes 1..{min(n, elo_K+2)})"
    elif elo_mode == "class":
        narrowing_info = (
            f" (class {elo_K}, R3 competes {max(1, elo_K-2)}..{min(n, elo_K+2)})"
        )

    lines = [
        f"# Elo Ranking \u2014 {len(ranked_ids)} of {n}{narrowing_info}\n",
        f"**Task:** {task}\n",
        f"**Provider:** {opts.provider} / {opts.model} ({opts.effort} effort)\n",
        f"**Rounds:** {n_rounds}\n",
        f"**Cache:** {cache_stats['cached']} hits\n",
        "\n## Final Ranking\n",
        "| Rank | Artifact       | Elo    | Matches |",
        "|------|----------------|--------|---------|",
    ]
    for rank, aid in enumerate(ranked_ids, 1):
        ae = result["artifacts"][aid]
        lines.append(f"| {rank}    | {ae['id']:<15} | {ae['elo']:6.1f} | {ae['n']:7} |")

    if rounds_log:
        lines.append("\n## Rounds Log")
        for rlog in rounds_log:
            lines.append(f"\n### Round {rlog['round']} \u2014 {len(rlog['pairs'])} matches")
            for m in rlog["pairs"]:
                lines.append(
                    f"- ({m['a']} {m['a_elo_after']:.0f}) vs ({m['b']} {m['b_elo_after']:.0f})"
                    f" \u2192 {m['winner']} | {m['reason'][:80]}"
                )

    return render_and_emit("\n".join(lines), opts.output)


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
    parser.add_argument(
        "artifacts",
        nargs="+",
        help="File paths, URLs, or inline:TEXT (put before --prompt)",
    )
    parser.add_argument(
        "--prompt", help="Task framing what good means (required)"
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Model name [default: claude-sonnet-4-6]",
    )
    parser.add_argument(
        "--provider",
        default="cli",
        help='Provider: "cli" (claude CLI) or an OpenAI-compatible base URL [default: cli]',
    )
    parser.add_argument(
        "--effort",
        default="high",
        help="Claude effort: low, medium, high [default: high]",
    )
    parser.add_argument(
        "--criteria", type=Path, help="Path to criteria JSON file"
    )
    parser.add_argument(
        "--criteria-text", help="Inline criteria as JSON string"
    )
    parser.add_argument(
        "--elo-rank",
        type=int,
        help="Elo mode: sorted top-K. R3 competes ranks 1..K+2. Best for EA top-K selection.",
    )
    parser.add_argument(
        "--elo-class",
        type=int,
        help="Elo mode: pivot top-K. R3 competes ranks K-2..K+2, returns top K. Best for EA survivor selection: cheaper than --elo-rank because R3 only judges the band around the cut line.",
    )
    parser.add_argument(
        "--rounds", type=int, default=3, help="Elo rounds [default: 3]"
    )
    parser.add_argument(
        "--output", help="Write output to file [default: stdout]"
    )
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
    opts = JudgeOpts(model=args.model, effort=args.effort, provider=args.provider, output=args.output)

    # Dispatch
    if args.mode == "review":
        mode_review(artifacts, criteria, task, opts)
    elif args.mode == "gate":
        mode_gate(artifacts, criteria, task, opts)
    elif args.mode == "elo":
        mode_elo(artifacts, criteria, task, opts, elo_mode, elo_K, args.rounds)


if __name__ == "__main__":
    main()
