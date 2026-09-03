"""Prompt builders for llm-judge: pairwise, critique, and gate evaluation."""

from __future__ import annotations


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
