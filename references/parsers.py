"""Result parsers for llm-judge: pairwise, gate, and review output parsers.

All parsers accept raw LLM output text and return a normalized dict.
Every parser strips reasoning-model <thinking> blocks first (see strip_thinking)
-- a judge verdict must never be read out of the model's scratchpad.
"""

from __future__ import annotations

import json
import re


def strip_thinking(raw: str) -> str:
    """Remove reasoning-model <thinking> scratchpad blocks from raw output.

    Reasoning providers (MiniMax et al.) wrap deliberation in <thinking>...</thinking>
    before the real answer. Left in, it defeats the JSON parse and then poisons the
    regex fallback, which reads the scratchpad as if it were the verdict.
    """
    return re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL)


def parse_pairwise_result(raw: str) -> dict:
    """Parse pairwise comparison output into structured result.

    Tries JSON first (on text with MiniMax <thinking> blocks stripped).
    Falls back to regex on cleaned text:
      - Winner: A/B
      - Score_A: N or Score_B: N or Score: N patterns

    Returns dict with a_score, b_score, winner, reason.
    """
    cleaned = strip_thinking(raw)
    try:
        data = json.loads(cleaned)
        return {
            "a_score": float(data["a_score"]),
            "b_score": float(data["b_score"]),
            "winner": data["winner"].upper(),
            "reason": data.get("reason", ""),
        }
    except Exception:
        pass
    winner = None
    for w in ("A", "B"):
        if re.search(rf'\bWinner:\s*{w}\b', cleaned, re.IGNORECASE):
            winner = w
            break
    scores = [float(s) for s in re.findall(r'Score[_ ]?[AB]?:\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)]
    a_score = scores[0] if len(scores) > 0 else 5.0
    b_score = scores[1] if len(scores) > 1 else 5.0
    winner = winner or ("A" if a_score > b_score else "B" if b_score > a_score else "A")
    return {"a_score": a_score, "b_score": b_score, "winner": winner, "reason": cleaned[:200]}


def parse_gate_result(raw: str) -> dict:
    """Parse gate evaluation output.

    Tries JSON first (on text with <thinking> blocks stripped), falls back to regex.
    Returns dict with score, passed, verdict.
    """
    cleaned = strip_thinking(raw)
    try:
        data = json.loads(cleaned)
        return {
            "score": float(data["score"]),
            "passed": bool(data.get("passed", float(data["score"]) >= 3.5)),
            "verdict": data.get("verdict", ""),
        }
    except Exception:
        score_match = re.search(r'Score:\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)
        score = float(score_match.group(1)) if score_match else 3.0
        passed = "pass" in cleaned.lower() or score >= 3.5
        verdict = cleaned[:200]
        return {"score": score, "passed": passed, "verdict": verdict}


def parse_review_result(raw: str) -> dict:
    """Parse critique/review output into structured result.

    Tries JSON first (on text with <thinking> blocks stripped). Unlike pairwise
    and gate there is no regex fallback -- a review is free-form prose, so a
    failed parse degrades to showing the raw text rather than guessing numbers.

    Returns dict with scores, feedback, average, and parsed (False when the JSON
    parse failed, in which case `raw` carries the unstructured response).
    """
    cleaned = strip_thinking(raw)
    try:
        data = json.loads(cleaned)
        return {
            "scores": data.get("scores", {}),
            "feedback": data.get("feedback", ""),
            "average": float(data.get("average", 0)),
            "parsed": True,
            "raw": cleaned,
        }
    except Exception:
        return {"scores": {}, "feedback": "", "average": 0.0,
                "parsed": False, "raw": cleaned}
