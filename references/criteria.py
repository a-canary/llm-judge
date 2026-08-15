"""Default criteria definitions and validation for llm-judge."""

from __future__ import annotations


DEFAULT_CRITERIA = {
    "dimensions": [
        {"name": "Correctness",     "weight": 0.30, "desc": "Does it do what it claims? No factual or logical errors?"},
        {"name": "Completeness",    "weight": 0.25, "desc": "All parts of the task addressed? Edge cases handled?"},
        {"name": "Clarity",         "weight": 0.20, "desc": "Intent obvious? Structure logical? No ambiguous terms?"},
        {"name": "Maintainability", "weight": 0.15, "desc": "Well-organized? No unnecessary complexity?"},
        {"name": "EdgeCases",       "weight": 0.10, "desc": "Failure modes addressed? Errors handled gracefully?"},
    ],
}


def validate_criteria(criteria: dict) -> None:
    """Validate that dimension weights sum to 1.0."""
    total = sum(d["weight"] for d in criteria["dimensions"])
    if abs(total - 1.0) > 0.001:
        raise ValueError(
            f"Criteria dimensions must sum to 1.0, got {total}. "
            f"Check: {[d['name'] for d in criteria['dimensions']]}"
        )
