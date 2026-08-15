"""Result parsers for llm-judge: pairwise, gate, and review output parsers.

All parsers accept raw LLM output text and return a normalized dict.
MiniMax thinking blocks are stripped before parsing where relevant.
"""

from __future__ import annotations

import json
import re


def parse_pairwise_result(raw: str) -> dict:
    """Parse pairwise comparison output into structured result.

    Tries JSON first (on text with MiniMax <thinking> blocks stripped).
    Falls back to regex on cleaned text:
      - Winner: A/B
      - Score_A: N or Score_B: N or Score: N patterns

    Returns dict with a_score, b_score, winner, reason.
    """
    cleaned = re.sub(r'<thinking>.*?</thinking>', '', raw, flags=re.DOTALL)
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

    Tries JSON first, falls back to regex.
    Returns dict with score, passed, verdict.
    """
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
