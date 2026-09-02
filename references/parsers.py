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

    Reasoning providers wrap deliberation in <thinking> (MiniMax) or <think>
    (DeepSeek, Qwen) before the real answer. Left in, it defeats the JSON parse and
    then poisons the regex fallback, which reads the scratchpad as if it were the
    verdict. An unclosed block is treated as scratchpad to end-of-text: a truncated
    response must not leak deliberation into a verdict.
    """
    return re.sub(r"<(thinking|think)>.*?(</\1>|$)", "", raw,
                  flags=re.DOTALL | re.IGNORECASE)


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

    The regex path fails CLOSED: `passed` requires an affirmative "Verdict: PASS"
    (or a parsed score over the bar), never the mere presence of the substring
    "pass" -- which also appears in "does not pass". Unparseable prose is a
    refusal, not an approval.

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
        score = float(score_match.group(1)) if score_match else 0.0
        affirmative = re.search(r'\bVerdict:\s*PASS\b', cleaned, re.IGNORECASE)
        passed = bool(affirmative) or (score_match is not None and score >= 3.5)
        verdict = cleaned[:200]
        return {"score": score, "passed": passed, "verdict": verdict}


def parse_review_result(raw: str) -> dict:
    """Parse critique/review output into structured result.

    Tries JSON first (on text with <thinking> blocks stripped). Unlike pairwise
    and gate there is no regex fallback -- a review is free-form prose, so a
    failed parse degrades to showing the raw text rather than guessing numbers.

    Returns dict with scores, feedback, average, and parsed. `parsed` is False
    both when the JSON parse failed and when it succeeded on JSON that is not a
    review payload -- a missing `average` must degrade to raw text, never render
    as a real 0.00/5. In either case `raw` carries the unstructured response.
    """
    cleaned = strip_thinking(raw)
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict) or not {"scores", "average"} <= data.keys():
            raise ValueError("not a review payload")
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
