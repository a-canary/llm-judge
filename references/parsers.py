"""Result parsers for llm-judge: pairwise, gate, and review output parsers.

All parsers accept raw LLM output text and return a normalized dict.
Every parser strips reasoning-model <thinking> blocks first (see strip_thinking)
-- a judge verdict must never be read out of the model's scratchpad.
"""

from __future__ import annotations

import json
import re
from typing import Optional


def strip_thinking(raw: str) -> str:
    """Remove reasoning-model <thinking> scratchpad blocks from raw output.

    Reasoning providers wrap deliberation in <thinking> (MiniMax) or <think>
    (DeepSeek, Qwen) before the real answer. Left in, it defeats the JSON parse and
    then poisons the regex fallback, which reads the scratchpad as if it were the
    verdict.

    Scanned left to right so a block never spans text between two blocks: a payload
    that merely mentions `<think>` followed by a real scratchpad must not have the
    span between them swallowed. Only closed blocks are stripped -- an unclosed tag
    is far more often a mention inside a payload than a truncated scratchpad, and a
    genuinely truncated one still fails safe via the failed parse.
    """
    out, pos = [], 0
    for m in re.finditer(r"<(?:thinking|think)>", raw, re.IGNORECASE):
        if m.start() < pos:
            continue
        close = re.compile(r"</(?:thinking|think)>", re.IGNORECASE).search(raw, m.end())
        if not close:
            break
        # Pair with the innermost open before this close: otherwise a payload
        # mention would swallow everything up to a *later* block's closing tag.
        inner = None
        for nxt in re.finditer(r"<(?:thinking|think)>", raw[m.end():close.start()],
                               re.IGNORECASE):
            inner = m.end() + nxt.start()
        if inner is not None:
            out.append(raw[pos:inner])
            pos = close.end()
            continue
        out.append(raw[pos:m.start()])
        pos = close.end()
    out.append(raw[pos:])
    return "".join(out)


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

    The regex path fails CLOSED and reads exactly ONE decision site: the first
    verdict-labelled line, else a lone verdict word on its own line. It does not
    scan the document for an affirmative-looking token -- that is what let a FAIL
    verdict be overridden by the word "pass" occurring later in the rationale.
    Anything else is a refusal, not an approval.

    Returns dict with score, passed, verdict, and `scored` -- False when no score
    was parseable, so callers render "--" instead of a fabricated 0.00/5.
    """
    cleaned = strip_thinking(raw)
    try:
        data = json.loads(cleaned)
        return {
            "score": float(data["score"]),
            "passed": bool(data.get("passed", float(data["score"]) >= 3.5)),
            "verdict": data.get("verdict", ""),
            "scored": True,
        }
    except Exception:
        pass
    score_match = re.search(r'Score:\s*(\d+\.?\d*)', cleaned, re.IGNORECASE)
    score = float(score_match.group(1)) if score_match else 0.0
    decision = _gate_decision(cleaned)
    if decision is None:
        # No decision site at all: a score over the bar is the only other signal.
        passed = score_match is not None and score >= 3.5
    else:
        passed = decision
    return {"score": score, "passed": passed, "verdict": cleaned[:200],
            "scored": score_match is not None}


# The verdict word, optionally decorated (**PASS**, `FAIL`), alone in its span.
_VERDICT_WORD = re.compile(r'^[\s*_`|]*(pass(?:ed)?|fail(?:ed)?|reject(?:ed)?)[\s*_`|.!]*$',
                           re.IGNORECASE)
# The same word opening a labelled value, which may carry a trailing rationale
# ("Verdict: PASS -- meets the bar"). Anchored at the start so the rationale can
# never supply the decision.
_VERDICT_LEAD = re.compile(r'^[\s*_`|]*(pass(?:ed)?|fail(?:ed)?|reject(?:ed)?)\b',
                           re.IGNORECASE)
_VERDICT_LABEL = re.compile(r'^[\s*_`|>#-]*(?:verdict|result|gate|status|decision|assessment)'
                            r'[\s*_`]*(?::|\|)[\s|]*(.+?)[\s|]*$', re.IGNORECASE)


def _gate_decision(cleaned: str) -> Optional[bool]:
    """Return the gate's decision from its ONE decision site, or None if absent.

    Checks each line for a verdict label and reads only that line's value; falls
    back to a line that is nothing but a verdict word. Returns None when neither
    exists, so the caller can fail closed rather than guess from stray prose.
    """
    lines = cleaned.splitlines()
    for line in lines:
        label = _VERDICT_LABEL.match(line)
        if label:
            value = label.group(1)
            # A markdown table row leaves the value padded with pipes. The word
            # must open the value -- never merely appear inside its rationale.
            word = _VERDICT_WORD.match(value) or _VERDICT_LEAD.match(value)
            return word.group(1).lower().startswith("pass") if word else False
    for line in lines:
        word = _VERDICT_WORD.match(line)
        if word:
            return word.group(1).lower().startswith("pass")
    return None


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
