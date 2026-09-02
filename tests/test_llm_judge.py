"""Unit tests for llm-judge — no live LLM calls."""

import json
import sys
import os

# Enable package-style imports from project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from references.artifacts import load_artifact
from references.criteria import validate_criteria
from references.elo import (
    FIFOCache,
    rank_swiss_elo,
    ArtifactElo,
    _compute_narrowing_schedule,
)
from references.parsers import (
    parse_gate_result,
    parse_pairwise_result,
    parse_review_result,
)
from references.providers import resolve_api_url


# ---------------------------------------------------------------------------
# parse_pairwise_result
# ---------------------------------------------------------------------------

def test_parse_pairwise_clean_json():
    raw = '{"a_score": 4.2, "b_score": 3.8, "winner": "A", "reason": "better"}'
    r = parse_pairwise_result(raw)
    assert r["winner"] == "A"
    assert r["a_score"] == 4.2
    assert r["b_score"] == 3.8


def test_parse_pairwise_winner_b():
    raw = '{"a_score": 1.0, "b_score": 5.0, "winner": "B"}'
    r = parse_pairwise_result(raw)
    assert r["winner"] == "B"


def test_parse_pairwise_thinking_block_stripped():
    """MiniMax injects <thinking>... op ...</thinking> before JSON."""
    raw = '<thinking>analyzing options op weighing</thinking>{"a_score": 4.0, "b_score": 3.0, "winner": "A"}'
    r = parse_pairwise_result(raw)
    assert r["winner"] == "A"
    assert r["a_score"] == 4.0


def test_parse_pairwise_fallback_regex():
    """Fallback when JSON parse fails."""
    raw = "Artifact A Score: 4.0\nArtifact B Score: 3.0\nWinner: A"
    r = parse_pairwise_result(raw)
    assert r["winner"] == "A"
    assert abs(r["a_score"] - 4.0) < 0.01


def test_parse_pairwise_fallback_defaults():
    """Fallback when no scores detected — defaults to 5.0."""
    raw = "This is a textual response without scores."
    r = parse_pairwise_result(raw)
    assert r["a_score"] == 5.0
    assert r["b_score"] == 5.0
    assert r["winner"] in ("A", "B")


# ---------------------------------------------------------------------------
# parse_gate_result  (sibling of parse_pairwise — same thinking strip)
# ---------------------------------------------------------------------------

def test_parse_gate_clean_json():
    raw = '{"score": 4.2, "passed": true, "verdict": "looks good"}'
    r = parse_gate_result(raw)
    assert r["score"] == 4.2
    assert r["passed"] is True
    assert r["verdict"] == "looks good"


def test_parse_gate_fallback_regex():
    """Fallback when JSON parse fails — regex extracts Score."""
    raw = "Score: 3.8\nOverall: pass"
    r = parse_gate_result(raw)
    assert abs(r["score"] - 3.8) < 0.01
    assert r["passed"] is True


def test_parse_gate_strips_thinking_before_verdict():
    """A gate verdict must come from the answer, never the <thinking> scratchpad.

    Reasoning providers (MiniMax) wrap deliberation in <thinking>. Left in, the
    JSON parse fails on the leading prefix and the regex fallback reads the
    scratchpad -- which fails OPEN: an explicit {"passed": false} is reported as
    a pass because the word "pass" appears in the deliberation.
    """
    raw = ('<thinking>The artifact does not pass the safety bar.</thinking>'
           '{"score": 1.0, "passed": false, "verdict": "unsafe"}')
    r = parse_gate_result(raw)
    assert r["passed"] is False
    assert abs(r["score"] - 1.0) < 0.01
    assert r["verdict"] == "unsafe"


def test_parse_gate_strips_thinking_in_regex_fallback():
    """Strip applies to the regex path too, not just the JSON path."""
    r = parse_gate_result('<thinking>Score: 1.0 is my draft</thinking>Score: 4.5\nVerdict: pass')
    assert abs(r["score"] - 4.5) < 0.01
    assert not r["verdict"].startswith("<thinking>")


# ---------------------------------------------------------------------------
# parse_review_result
# ---------------------------------------------------------------------------

def test_parse_review_clean_json():
    raw = '{"scores": {"Clarity": 4}, "feedback": "solid", "average": 4.0}'
    r = parse_review_result(raw)
    assert r["parsed"] is True
    assert r["scores"]["Clarity"] == 4
    assert r["feedback"] == "solid"
    assert abs(r["average"] - 4.0) < 0.01


def test_parse_review_strips_thinking():
    raw = '<thinking>weighing it up</thinking>{"scores": {}, "feedback": "ok", "average": 3.0}'
    r = parse_review_result(raw)
    assert r["parsed"] is True
    assert r["feedback"] == "ok"


def test_parse_review_unparseable_keeps_raw():
    """Prose review must degrade to raw text, never to invented numbers."""
    r = parse_review_result("This essay reads well but rambles.")
    assert r["parsed"] is False
    assert r["average"] == 0.0
    assert "rambles" in r["raw"]


# ---------------------------------------------------------------------------
# resolve_api_url
# ---------------------------------------------------------------------------

def test_resolve_api_url_cli():
    assert resolve_api_url("cli") == "cli"


def test_resolve_api_url_passes_through_url():
    assert resolve_api_url("https://api.minimax.io/v1") == "https://api.minimax.io/v1"


def test_resolve_api_url_rejects_non_url_provider(monkeypatch):
    """A typo'd provider must fail loudly, not become an empty base URL."""
    monkeypatch.delenv("LLM_JUDGE_API_BASE", raising=False)
    import pytest
    with pytest.raises(ValueError):
        resolve_api_url("minmax")


# ---------------------------------------------------------------------------
# validate_criteria
# ---------------------------------------------------------------------------

def test_validate_criteria_valid():
    criteria = {"dimensions": [{"name": "X", "weight": 0.5}, {"name": "Y", "weight": 0.5}]}
    validate_criteria(criteria)  # no raise


def test_validate_criteria_sum_must_be_1():
    criteria = {"dimensions": [{"name": "X", "weight": 0.3}, {"name": "Y", "weight": 0.3}]}
    import pytest
    with pytest.raises(ValueError):
        validate_criteria(criteria)


# ---------------------------------------------------------------------------
# load_artifact
# ---------------------------------------------------------------------------

def test_load_artifact_inline():
    a = load_artifact("inline:Hello world")
    assert a["id"].startswith("artifact_")
    assert a["content"] == "Hello world"
    assert len(a["content_hash"]) == 16


def test_load_artifact_path(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("file content")
    a = load_artifact(str(f))
    assert a["id"] == "test.txt"
    assert a["content"] == "file content"


def test_load_artifact_url():
    a = load_artifact("https://example.com/")
    assert "example.com" in a["id"] or a["id"] == "example.com"


def test_load_artifact_content_hash_stable():
    a1 = load_artifact("inline:same")
    a2 = load_artifact("inline:same")
    assert a1["content_hash"] == a2["content_hash"]


# ---------------------------------------------------------------------------
# FIFOCache
# ---------------------------------------------------------------------------

def _fresh_cache(max_size=128):
    """Create a FIFOCache with an isolated temp backing file."""
    from references import elo as em
    old = em.CACHE_PATH
    path = old.parent / f"_test_cache_{os.getpid()}_{id(object())}.json"
    em.CACHE_PATH = path
    cache = FIFOCache(max_size=max_size)
    em.CACHE_PATH = old
    return cache, path


def test_fifo_cache_miss_returns_none():
    cache, path = _fresh_cache(128)
    try:
        assert cache.get("task", "dims", "a1", "h1", "b1", "h2") is None
    finally:
        if path.exists():
            path.unlink()


def test_fifo_cache_set_and_get():
    cache, path = _fresh_cache(128)
    try:
        key = ("task", "dims", "a1", "h1", "b1", "h2")
        cache.set(*key, {"result": "ok"})
        assert cache.get(*key) == {"result": "ok"}
    finally:
        if path.exists():
            path.unlink()


def test_fifo_cache_eviction():
    cache, path = _fresh_cache(2)
    try:
        for i in range(3):
            cache.set("t", "d", f"a{i}", "h", f"b{i}", "h", {"v": i})
        assert cache.get("t", "d", "a0", "h", "b0", "h") is None
        assert cache.get("t", "d", "a1", "h", "b1", "h") is not None
        assert cache.get("t", "d", "a2", "h", "b2", "h") is not None
    finally:
        if path.exists():
            path.unlink()


def test_fifo_cache_symmetry():
    cache, path = _fresh_cache(128)
    try:
        cache.set("task", "dims", "A", "aaa", "B", "bbb", {"winner": "A"})
        hit = cache.get("task", "dims", "B", "bbb", "A", "aaa")
        assert hit is not None and hit["winner"] == "A"
    finally:
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# rank_swiss_elo — invariants
# ---------------------------------------------------------------------------

def test_rank_swiss_elo_returns_correct_keys():
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [
        {"id": "a", "content_hash": "h1", "content": "aaa"},
        {"id": "b", "content_hash": "h2", "content": "bbb"},
    ]
    result = rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=1)
    assert "ranked" in result
    assert "artifacts" in result
    assert "rounds_log" in result
    assert isinstance(result["ranked"], list)


def test_rank_swiss_elo_ranked_is_list_of_ids():
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [
        {"id": "a", "content_hash": "h1", "content": "aaa"},
        {"id": "b", "content_hash": "h2", "content": "bbb"},
        {"id": "c", "content_hash": "h3", "content": "ccc"},
    ]
    result = rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=1)
    # Seeding is (Elo desc, id asc), so with all Elos tied at 1500 the pair is
    # (a, b) and c byes. "B" always wins, so b tops and the loser a sinks below
    # the untouched bye.
    assert result["ranked"] == ["b", "c", "a"]
    assert set(result["ranked"]) == {"a", "b", "c"}
    assert result["artifacts"]["c"]["elo"] == 1500  # bye is not scored


def test_rank_swiss_elo_bye_handling():
    """Odd number of artifacts — one gets a bye each round."""
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [
        {"id": "a", "content_hash": "h1", "content": "aaa"},
        {"id": "b", "content_hash": "h2", "content": "bbb"},
        {"id": "c", "content_hash": "h3", "content": "ccc"},
    ]
    result = rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=1)
    assert len(result["byes"]) == 1
    assert len(result["byes"][0]) == 1  # exactly one bye


def test_rank_swiss_elo_compare_fn_receives_artifact_elo_objects():
    """compare_fn receives ArtifactElo objects, not id/elo/content tuples."""
    cache = FIFOCache()
    received = []

    def compare_fn(task, dims_hash, a, b, cache):
        received.append((type(a).__name__, type(b).__name__))
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [{"id": "a", "content_hash": "h1", "content": "aaa"}]
    rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=1)
    assert all(t == "ArtifactElo" for t in received)


def test_rank_swiss_elo_past_elos_respected():
    """Artifacts with prior Elo start there, not at 1500."""
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [
        {"id": "a", "content_hash": "h1", "content": "aaa"},
        {"id": "b", "content_hash": "h2", "content": "bbb"},
    ]
    result = rank_swiss_elo(
        artifacts, "task", "hash", cache, compare_fn,
        past_elos={"a": 1700.0}, n_rounds=1
    )
    assert result["artifacts"]["a"]["elo"] > 1500


def test_rank_swiss_elo_round_record_no_legacy_eliminated_key():
    """Architecture-hygiene: the dead `eliminated` field is no longer emitted;
    narrowed-out artifacts are reported only via `byes`."""
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [{"id": str(i), "content_hash": f"h{i}", "content": f"c{i}"} for i in range(6)]
    result = rank_swiss_elo(
        artifacts, "task", "hash", cache, compare_fn,
        n_rounds=3, elo_mode="rank", elo_K=2,
    )
    for rlog in result["rounds_log"]:
        assert "eliminated" not in rlog, (
            f"round {rlog['round']} still emits legacy 'eliminated' key: {rlog}"
        )


def test_rank_swiss_elo_no_repeat_pairings():
    """Same pair never meets twice across rounds."""
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [{"id": str(i), "content_hash": f"h{i}", "content": f"c{i}"} for i in range(4)]
    result = rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=3)
    seen_pairs = set()
    for rlog in result["rounds_log"]:
        for pair in rlog["pairs"]:
            pair_key = frozenset({pair["a"], pair["b"]})
            assert pair_key not in seen_pairs, f"Repeat pairing: {pair}"
            seen_pairs.add(pair_key)

def test_rank_swiss_elo_compare_fn_receives_content():
    """ArtifactElo carries content, so compare_fn needs no id->content side-table."""
    cache = FIFOCache()
    seen = {}

    def compare_fn(task, dims_hash, a, b, cache):
        seen[a.id] = a.content
        seen[b.id] = b.content
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [
        {"id": "a", "content_hash": "h1", "content": "aaa"},
        {"id": "b", "content_hash": "h2", "content": "bbb"},
    ]
    rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=1)
    assert seen == {"a": "aaa", "b": "bbb"}


def test_class_mode_r3_competes_the_cut_band_not_the_leaders():
    """`--elo-class K` exists to be cheaper than `--elo-rank K` by racing only
    the ranks straddling the cut. Regression guard: the schedule used to be a
    bare count, which silently raced ranks 1..K (the leaders) instead."""
    rank = _compute_narrowing_schedule(20, 3, "rank", 5)
    klass = _compute_narrowing_schedule(20, 3, "class", 5)

    assert rank[2] == (1, 7)     # leaders re-race
    assert klass[2] == (3, 7)    # band straddles the cut at 5/6
    # the point of class mode: strictly fewer comparisons than rank mode
    def width(b):
        return b[1] - b[0] + 1
    assert width(klass[2]) < width(rank[2])


def test_narrowing_bands_are_capped_and_disabled_when_K_exceeds_N():
    assert _compute_narrowing_schedule(4, 3, "class", 5) == [(1, 4)] * 3   # K >= N
    assert _compute_narrowing_schedule(6, 3, "class", 2) == [(1, 6), (1, 6), (1, 4)]
    assert _compute_narrowing_schedule(6, 3, "all", 0) == [(1, 6)] * 3


def test_class_mode_byes_the_artifacts_outside_the_cut_band():
    """Artifacts above and below the R3 band both sit out that round."""
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "winner": "B", "reason": "test"}

    artifacts = [
        {"id": f"a{i}", "content_hash": f"h{i}", "content": f"c{i}"} for i in range(8)
    ]
    result = rank_swiss_elo(
        artifacts, "task", "hash", cache, compare_fn,
        n_rounds=3, elo_mode="class", elo_K=4,
    )
    r3 = result["rounds_log"][2]
    assert r3["competing_ranks"] == [2, 6]   # K-2 .. K+2
    # ranks 1, 7, 8 sit out from narrowing; the 5-artifact band is odd, so one
    # in-band artifact byes for lack of a partner too.
    assert len(r3["byes"]) == 4
    assert len(result["ranked"]) == 4        # output still trimmed to top K


def test_gate_fails_closed_on_negated_pass():
    """"does not pass" must not read as a pass.

    The substring test `"pass" in raw.lower()` matched the word inside its own
    negation, so an explicit FAIL verdict reported passed=True. A safety gate
    requires an affirmative signal, never the mere presence of the word.
    """
    for prose in ("Verdict: FAIL. This does not pass the safety bar.",
                  "The document fails. I would not pass this."):
        assert parse_gate_result(prose)["passed"] is False, prose


def test_gate_fails_closed_on_unparseable_prose():
    """No parseable verdict is a refusal, not an approval."""
    r = parse_gate_result("The response was empty.")
    assert r["passed"] is False
    assert r["score"] == 0.0


def test_gate_accepts_affirmative_verdict():
    """Fail-closed must not become fail-always: real approvals still pass.

    Judges decorate their verdicts. If only the bare literal "Verdict: PASS"
    were accepted, the gate would block good artifacts -- a usability
    regression as real as the fail-open bug, just quieter.
    """
    for raw in ("Verdict: PASS -- meets the bar.", "Score: 4.5 solid work",
                "Verdict: **PASS**", "verdict: pass", "Verdict:PASS",
                "Result: PASS", "Gate: PASSED", "PASSED", "**PASS**"):
        assert parse_gate_result(raw)["passed"] is True, raw


def test_strip_thinking_covers_tag_variants():
    """<think> (DeepSeek/Qwen), odd casing, and unclosed blocks are all scratchpad.

    Stripping only lowercase <thinking> left the identical fail-open bug one tag
    name away: the deliberation survived and the regex fallback read it.
    """
    payload = '{"score": 1.0, "passed": false, "verdict": "unsafe"}'
    for raw in (f'<Thinking>does not pass</Thinking>{payload}',
                f'<think>does not pass</think>{payload}'):
        r = parse_gate_result(raw)
        assert r["passed"] is False, raw
        assert r["verdict"] == "unsafe"
    # Mismatched open/close still strips: real output pairs them loosely.
    assert parse_gate_result(f'<thinking>bad</think>{payload}')["passed"] is False
    # Truncated mid-scratchpad: no verdict was ever emitted, so it must not pass.
    assert parse_gate_result("<thinking>this would pass")["passed"] is False


def test_strip_thinking_leaves_unclosed_tag_in_payload_alone():
    """An unclosed tag inside a real payload is a mention, not a scratchpad.

    Stripping `<think>` to end-of-text destroyed valid output: a judge that
    passed an artifact whose verdict merely mentioned the tag was rendered as
    a hard FAIL. Only closed blocks are scratchpad.
    """
    r = parse_gate_result('{"score":4.5,"passed":true,"verdict":"no <think> needed"}')
    assert r["passed"] is True
    assert abs(r["score"] - 4.5) < 0.01
    rv = parse_review_result(
        '{"scores":{"Clarity":4},"average":4.0,"feedback":"Avoid <think> tags"}')
    assert rv["parsed"] is True
    assert abs(rv["average"] - 4.0) < 0.01


def test_gate_marks_unscored_verdicts():
    """A verdict with no parseable score must not render as a real 0.00/5.

    Same fabricated-score defect as the review parser: 0.0 as a no-signal
    sentinel is indistinguishable from a genuine failing score.
    """
    r = parse_gate_result("Verdict: PASS")
    assert r["passed"] is True and r["scored"] is False
    assert parse_gate_result("Score: 4.5 good")["scored"] is True
    assert parse_gate_result('{"score":1.0,"passed":false}')["scored"] is True


def test_parse_review_rejects_wrong_shaped_json():
    """Valid JSON that isn't a review must not surface as a real 0.00/5 score."""
    for raw in ('{"scores": {"Clarity": 4}}', '["not", "a", "review"]', '42'):
        assert parse_review_result(raw)["parsed"] is False, raw
