"""Unit tests for llm-judge — no live LLM calls."""

import json
import sys
import os

import pytest

# Enable package-style imports from project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, ROOT)
sys.path.insert(0, SCRIPTS)

from references.elo import FIFOCache, rank_swiss_elo, ArtifactElo
from run_judge import (
    parse_pairwise_result,
    parse_gate_result,
    validate_criteria,
    load_artifact,
)


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Point the module-level cache file at tmp_path for every test.

    FIFOCache() reads CACHE_PATH on construction and writes it on save, so
    without this the suite reads and rewrites the operator's real
    ~/.cache/llm-judge/fifo_cache.json.
    """
    from references import elo as em
    monkeypatch.setattr(em, "CACHE_PATH", tmp_path / "fifo_cache.json")


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
# parse_gate_result  (sibling of parse_pairwise — same helper, no thinking strip)
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


def test_parse_gate_no_thinking_strip():
    """Gate callers do not strip <thinking> by default (strip_thinking=False).

    Pins the default by embedding a complete JSON payload INSIDE a <thinking>
    block followed by a regex-style score. With strip_thinking=True the JSON
    would parse first (score=2.0, failed); with the default strip_thinking=False
    the JSON is malformed and regex picks up Score: 4.5. The two outputs are
    distinguishable, so this test fails if the default ever flips.
    """
    raw = '<thinking>{"score": 2.0, "passed": false}</thinking>Score: 4.5\nVerdict: pass'
    r = parse_gate_result(raw)
    # Default strip_thinking=False: text is not stripped, JSON.parse fails on
    # the leading "<thinking>" prefix, regex fallback extracts "Score: 4.5".
    assert abs(r["score"] - 4.5) < 0.01
    # And the verdict came from regex fallback (truncated to 200 chars).
    assert r["verdict"].startswith("<thinking>")


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
    """Create a FIFOCache; _isolate_cache already redirects CACHE_PATH to tmp_path."""
    return FIFOCache(max_size=max_size)


def test_fifo_cache_miss_returns_none():
    cache = _fresh_cache(128)
    assert cache.get("task", "dims", "a1", "h1", "b1", "h2") is None


def test_fifo_cache_set_and_get():
    cache = _fresh_cache(128)
    key = ("task", "dims", "a1", "h1", "b1", "h2")
    cache.set(*key, {"result": "ok"})
    assert cache.get(*key)["result"] == "ok"


def test_fifo_cache_eviction():
    cache = _fresh_cache(2)
    for i in range(3):
        cache.set("t", "d", f"a{i}", "h", f"b{i}", "h", {"v": i})
    assert cache.get("t", "d", "a0", "h", "b0", "h") is None
    assert cache.get("t", "d", "a1", "h", "b1", "h") is not None
    assert cache.get("t", "d", "a2", "h", "b2", "h") is not None


def test_fifo_cache_symmetry():
    """(x,y) and (y,x) hit the same entry — the pair order must not miss."""
    cache = _fresh_cache(128)
    cache.set("task", "dims", "x", "aaa", "y", "bbb", {"winner": "A"})
    assert cache.get("task", "dims", "y", "bbb", "x", "aaa") is not None


def test_fifo_cache_reorients_winner_on_reversed_lookup():
    """The key is order-insensitive but "winner" is positional, so a reversed
    hit must be re-oriented. Regression: it used to return the stored letter
    verbatim, silently inverting the verdict."""
    cache = _fresh_cache(128)
    # x beat y (x was in position A when judged).
    cache.set("task", "dims", "x", "aaa", "y", "bbb",
              {"a_score": 5.0, "b_score": 1.0, "winner": "A", "reason": "x won"})

    same = cache.get("task", "dims", "x", "aaa", "y", "bbb")
    assert same["winner"] == "A", same          # x still in position A
    assert same["a_score"] == 5.0, same

    flipped = cache.get("task", "dims", "y", "bbb", "x", "aaa")
    assert flipped["winner"] == "B", flipped    # x is now position B
    assert flipped["a_score"] == 1.0, flipped   # scores follow the flip
    assert flipped["b_score"] == 5.0, flipped


def test_fifo_cache_drops_prefix_entries_without_winner_id():
    """Entries written before the id-keyed fix carry a positional "winner"
    that cannot be re-oriented — they must be dropped, not trusted, and must
    not crash the caller."""
    cache = _fresh_cache(128)
    key = cache._make_key("task", "dims", "x", "aaa", "y", "bbb")
    cache._data[key] = {"a_score": 5.0, "b_score": 1.0, "winner": "A"}
    assert cache.get("task", "dims", "x", "aaa", "y", "bbb") is None
    assert key not in cache._data


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
    # b wins every match, so b first
    assert result["ranked"] == ["b", "a", "c"]
    assert set(result["ranked"]) == {"a", "b", "c"}


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

# ---------------------------------------------------------------------------
# Seam: parse_pairwise_result output -> rank_swiss_elo compare_fn contract
# ---------------------------------------------------------------------------

def test_mode_elo_compare_fn_honours_judge_verdict():
    """mode_elo's compare_fn must pass the judge's winner through to the
    tournament. Regression: it emitted a_wins/b_wins/draw and dropped
    "winner", so rank_swiss_elo defaulted every match to an A win.

    The judge here always picks the artifact in position B, so the buggy
    default ("A") produces the opposite ranking — a mock that picked a fixed
    artifact would pass either way, since Swiss pairing chooses the order.
    """
    import run_judge

    seen_positions = []

    def fake_call(prompt, *a, **k):
        # Record which artifact landed in each position, then always pick B.
        seen_positions.append((prompt.index("aaa"), prompt.index("bbb")))
        return '{"a_score": 1.0, "b_score": 5.0, "winner": "B", "reason": "B won"}'

    orig_call = run_judge.call_claude
    orig_cache = run_judge._elo.FIFOCache
    run_judge.call_claude = fake_call
    run_judge._elo.FIFOCache = lambda *a, **k: _NullCache()
    try:
        artifacts = [
            {"id": "a", "content_hash": "h1", "content": "aaa"},
            {"id": "b", "content_hash": "h2", "content": "bbb"},
        ]
        criteria = {"dimensions": [{"name": "quality", "weight": 1.0, "desc": "d"}]}
        out = run_judge.mode_elo(
            artifacts, criteria, "task", run_judge.JudgeOpts(),
            elo_mode="all", elo_K=0, n_rounds=1,
        )
    finally:
        run_judge.call_claude = orig_call
        run_judge._elo.FIFOCache = orig_cache

    assert seen_positions, "judge was never called"
    a_pos, b_pos = seen_positions[0]
    # Whichever artifact Swiss pairing put in position B is the one that won.
    winner_id = "b" if b_pos > a_pos else "a"
    assert f"| 1    | {winner_id}" in out, (winner_id, out)


def test_rank_swiss_elo_rejects_result_without_winner():
    """A compare_fn that omits 'winner' must fail loudly, not score A wins."""
    cache = FIFOCache()

    def compare_fn(task, dims_hash, a, b, cache):
        return {"a_score": 3.0, "b_score": 4.0, "reason": "no winner key"}

    artifacts = [
        {"id": "a", "content_hash": "h1", "content": "aaa"},
        {"id": "b", "content_hash": "h2", "content": "bbb"},
    ]
    try:
        rank_swiss_elo(artifacts, "task", "hash", cache, compare_fn, n_rounds=1)
    except ValueError as e:
        assert "winner" in str(e)
    else:
        raise AssertionError("expected ValueError for missing 'winner'")


class _NullCache:
    """In-memory stand-in so the seam test never touches ~/.cache/llm-judge/."""

    def get(self, *a, **k):
        return None

    def set(self, *a, **k):
        return None

    def stats(self):
        return {"cached": 0, "max": 0}
