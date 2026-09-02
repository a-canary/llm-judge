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

    Tags are matched by DEPTH, so a nested block collapses into its outer block
    rather than closing it early -- pairing an outer open with an inner close would
    leave the outer block's tail (and any verdict in it) in the output.

    Only balanced blocks are stripped: an unclosed tag is far more often a mention
    inside a payload (`"verdict": "no <think> needed"`) than a truncated scratchpad,
    and stripping to end-of-text would destroy valid output. A genuinely truncated
    block still fails safe via the failed parse.
    """
    tags = list(re.finditer(r"</?(?:thinking|think)>", raw, re.IGNORECASE))
    spans, i = [], 0
    while i < len(tags):
        if tags[i].group().startswith("</"):
            i += 1  # stray close: nothing is open, so there is no block to end
            continue
        # Walk forward tracking depth, so a nested block collapses into this one
        # instead of closing it early and leaking the outer block's tail.
        depth, j = 1, i + 1
        while j < len(tags) and depth:
            depth += -1 if tags[j].group().startswith("</") else 1
            j += 1
        if depth:
            # Never closed: a mention inside a payload, not a scratchpad. Skip only
            # this tag -- a later balanced block must still be strippable.
            i += 1
            continue
        spans.append((tags[i].start(), tags[j - 1].end()))
        i = j
    out, pos = [], 0
    for start, end in spans:
        out.append(raw[pos:start])
        pos = end
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


# The vocabulary a judge actually uses to decide. Kept explicit and symmetric: an
# affirmative the reader does not recognise is treated as no decision, which fails
# closed, so a missing approval word blocks good artifacts until it is listed here.
_AFFIRM = r'pass(?:ed)?|approve[ds]?|accept(?:ed)?|yes'
_DENY = r'fail(?:ed|s)?|reject(?:ed|s)?|deny|denied|no'

# The verdict word, optionally decorated (**PASS**, `FAIL`), alone in its span.
_VERDICT_WORD = re.compile(r'^[\s*_`|]*(' + _AFFIRM + r'|' + _DENY + r')[\s*_`|.!]*$',
                           re.IGNORECASE)
# The same word opening a labelled value, which may carry a trailing rationale
# ("Verdict: PASS -- meets the bar"). Anchored at the start so the rationale can
# never supply the decision.
_VERDICT_LEAD = re.compile(r'^[\s*_`|]*(' + _AFFIRM + r'|' + _DENY + r')\b',
                           re.IGNORECASE)
# A qualifier after the verdict word withholds the approval it looks like it gives:
# "PASS with reservations" is not a pass. Only rejections may be qualified.
_HEDGE = re.compile(r'\b(with|pending|conditional|subject to|once|after|if|but|however|'
                    r'provided|assuming|contingent|caveat)\b', re.IGNORECASE)
_VERDICT_LABEL = re.compile(r'^[\s*_`|>#-]*(?:verdict|result|gate|status|decision|assessment)'
                            r'[\s*_`]*(?::|\|)[\s|]*(.+?)[\s|]*$', re.IGNORECASE)
_FENCE = re.compile(r'^[\s>]*(?:```|~~~)')
# A table row. Its cells only vote when the table declares a verdict column --
# an arbitrary last column ("| Blocking |" holding "No") is not a verdict.
_ROW_CELL = re.compile(r'^[\s>]*\|.*\|[\s>]*$')
_VERDICT_HEAD = re.compile(r'^[\s*_`]*(?:verdict|result|gate|status|decision|assessment)'
                           r'[\s*_`]*$', re.IGNORECASE)


def _decision_lines(cleaned: str):
    """Yield the lines that may carry a decision, skipping fenced code blocks.

    A fenced block quotes an example ("respond like: Verdict: PASS"), never the
    model's own verdict, so a decoy inside one must not get a vote.
    """
    fenced = False
    for line in cleaned.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield line


def _verdict_of(value: str) -> Optional[bool]:
    """Read a verdict word from the start of `value`, or None if it opens with none."""
    word = _VERDICT_WORD.match(value) or _VERDICT_LEAD.match(value)
    if not word:
        return None
    if not re.match(_AFFIRM + r'$', word.group(1), re.IGNORECASE):
        return False
    # An approval that carries a condition is a rejection until the condition is met.
    return not _HEDGE.search(value[word.end(1):])


def _gate_decision(cleaned: str) -> Optional[bool]:
    """Return the gate's decision, or None when the output states none.

    Reads EVERY decision site rather than the first, and any rejection dominates:
    one response may cover several artifacts, or reject after quoting an approval,
    and a gate that stops at the first site approves the whole batch on the
    strength of its first line. A decision is a verdict-labelled line's value or a
    line that is nothing but a verdict word, or a cell in a declared verdict
    column; prose can never supply one.

    Returns None when no site exists at all, so the caller fails closed rather
    than guessing.
    """
    seen, verdict_col = None, None
    for line in _decision_lines(cleaned):
        label = _VERDICT_LABEL.match(line)
        if label:
            # A markdown header row ("| Criterion | Verdict |") matches the label but
            # names a column instead of deciding -- it is not a site at all.
            decision = _verdict_of(label.group(1))
            if decision is None:
                continue
        elif _ROW_CELL.match(line):
            cells = [c.strip() for c in line.strip().strip('>| ').split('|')]
            heads = [i for i, c in enumerate(cells) if _VERDICT_HEAD.match(c)]
            if heads:
                # Header row: it names the verdict column rather than deciding.
                verdict_col = heads[-1]
                continue
            # Only that column votes. Any other ("| Blocking | No |") is not a
            # verdict, and reading it as one blocks artifacts the judge approved.
            if verdict_col is None or verdict_col >= len(cells):
                continue
            decision = _verdict_of(cells[verdict_col])
            if decision is None:
                continue
        else:
            word = _VERDICT_WORD.match(line)
            if not word:
                continue
            decision = _verdict_of(line)
        if decision is False:
            return False
        seen = True
    return seen


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
