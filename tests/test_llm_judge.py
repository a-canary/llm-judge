"""Unit tests for llm-judge — no live LLM calls."""

import json
import sys
import os
import hashlib

# Ensure references/elo is importable via 'references.elo'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "references"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from references.elo import FIFOCache, rank_swiss_elo, ArtifactElo
from run_judge import (
    parse_pairwise_result,
    validate_criteria,
    load_artifact,
)


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
    import references.elo as em
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