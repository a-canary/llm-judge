#!/usr/bin/env python3
"""
Swiss Elo ranking engine for llm-judge.

Algorithm (3 rounds, Monrad Swiss):

  Round 1: Sort by Elo desc + id asc. Attempt adjacent pairs.
           If (A,B) was already compared, try swapping B with next unpaired.
           If no novel partner exists, A gets a bye.

  Subsequent rounds: Same — re-sort by current Elo, pair adjacent with
                     repeat-swap fallback.

Elo update after each match:
  expected = 1 / (1 + 10 ** ((opponent_elo - my_elo) / 400))
  new_elo  = my_elo + 32 * (actual - expected)
  actual = 1.0 (win), 0.0 (loss), 0.5 (draw)

Seeding (Round 0):
  Each artifact starts at Elo = 1500.
  If a prior run recorded a prior Elo for this (task + artifact_id) pair, use it.

Monrad Swiss pairing invariants:
  - No repeat pairings (tracked via frozenset of seen pairs)
  - Same-score artifacts kept together (adjacent pairing)
  - Odd counts handled via byes (no comparison needed)

Cache (FIFO, max 512 entries):
  key = sha256(f"{task}:{dims_hash}:{sorted_pair}:{hashes[:8]}".encode()).hexdigest()
  value = {"a_score", "b_score", "winner", "reason"}
  Evicts oldest entry when cap is reached.
"""

from __future__ import annotations
import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CACHE_PATH = Path.home() / ".cache" / "llm-judge" / "fifo_cache.json"
CACHE_MAX = 512
K_FACTOR = 32
INITIAL_ELO = 1500


# ---------------------------------------------------------------------------
# FIFO Cache
# ---------------------------------------------------------------------------

class FIFOCache:
    """
    Simple FIFO cache keyed by sha256(task+dims+ids+hashes).
    Prevents duplicate Opus calls for identical comparison requests.

    The backing file is per-instance (`path`), not a module global — tests and
    concurrent runs can point at their own file without patching the module.
    """

    def __init__(self, max_size: int = CACHE_MAX, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else CACHE_PATH
        self._data: OrderedDict = OrderedDict(self._load())
        self._max = max_size

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(dict(self._data), indent=2))

    def _make_key(self, task: str, dims_hash: str,
                  a_id: str, a_hash: str,
                  b_id: str, b_hash: str) -> str:
        """Stable key — (a_id,b_id) always sorted so (A,B) and (B,A) collide."""
        if a_id < b_id:
            pair = f"{a_id}:{a_hash[:8]}|{b_id}:{b_hash[:8]}"
        else:
            pair = f"{b_id}:{b_hash[:8]}|{a_id}:{a_hash[:8]}"
        # v2: pre-v2 entries stored win/draw flags but no "winner" key, so the
        # engine silently scored every cache hit as an A-win. Namespacing the key
        # retires those entries instead of trusting them.
        return hashlib.sha256(f"v2:{task}:{dims_hash}:{pair}".encode()).hexdigest()

    def get(self, task: str, dims_hash: str,
            a_id: str, a_hash: str,
            b_id: str, b_hash: str) -> Optional[dict]:
        key = self._make_key(task, dims_hash, a_id, a_hash, b_id, b_hash)
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def set(self, task: str, dims_hash: str,
            a_id: str, a_hash: str,
            b_id: str, b_hash: str,
            result: dict) -> None:
        key = self._make_key(task, dims_hash, a_id, a_hash, b_id, b_hash)
        self._data[key] = result
        self._data.move_to_end(key)
        if len(self._data) > self._max:
            self._data.popitem(last=False)   # evict oldest
        self._save()

    def stats(self) -> dict:
        return {"cached": len(self._data), "max": self._max}


# ---------------------------------------------------------------------------
# Elo Tracker
# ---------------------------------------------------------------------------

@dataclass
class ArtifactElo:
    id: str
    content_hash: str
    elo: float = INITIAL_ELO
    matches: list[dict] = field(default_factory=list)   # record of each match

    def record(self, my_score: float, opponent_id: str, opponent_elo: float,
               winner: str, reason: str) -> None:
        expected = 1.0 / (1.0 + 10 ** ((opponent_elo - self.elo) / 400.0))
        actual = 1.0 if winner == "me" else 0.0 if winner == "opp" else 0.5
        self.elo = self.elo + K_FACTOR * (actual - expected)
        self.matches.append({
            "opponent": opponent_id,
            "my_score": my_score,
            "opponent_elo": opponent_elo,
            "winner": winner,
            "reason": reason,
        })

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content_hash": self.content_hash,
            "elo": round(self.elo, 1),
            "n": len(self.matches),
            "matches": self.matches,
        }


# ---------------------------------------------------------------------------
# Swiss pairing (Monrad)
# ---------------------------------------------------------------------------

def _swiss_pairs(
    artifacts: list[ArtifactElo],
    seen_pairs: set[frozenset],
) -> list[tuple[ArtifactElo, ArtifactElo]]:
    """
    Standard Monrad Swiss pairing:

    1. Sort all artifacts by (Elo desc, id asc) for stable tiebreaking
    2. Attempt adjacent pairs: (0,1), (2,3), ...
    3. For each proposed pair, if (A,B) was already seen in a prior round,
       try swapping B with the next unpaired artifact.
       If no novel partner exists, A gets a bye.
    4. Return list of (a, b) tuples; unpaired artifacts get byes.

    This guarantees no repeat pairings and same-score artifacts stay adjacent.
    """
    # Sort by Elo desc, then id asc for stable tiebreaking
    unpaired = sorted(artifacts, key=lambda a: (a.elo, a.id), reverse=True)
    pairs: list[tuple[ArtifactElo, ArtifactElo]] = []

    while unpaired:
        a = unpaired.pop(0)
        partner = None

        # Look for the first novel partner in Elo order
        for j, b in enumerate(unpaired):
            pair_key = frozenset({a.id, b.id})
            if pair_key not in seen_pairs:
                partner = j
                break
            # Mark already-seen rejection so we don't try (a, b) again later
            seen_pairs.add(pair_key)

        if partner is not None:
            b = unpaired.pop(partner)
            pairs.append((a, b))
        # else: no novel partner — a gets a bye and is dropped from unpaired

    return pairs


# ---------------------------------------------------------------------------
# Main rank function
# ---------------------------------------------------------------------------

def rank_swiss_elo(
    artifacts: list[dict],
    task: str,
    dims_hash: str,
    cache: FIFOCache,
    compare_fn,   # (a: ArtifactElo, b: ArtifactElo) -> dict, called only on cache miss
    past_elos: Optional[dict[str, float]] = None,
    n_rounds: int = 3,
    elo_mode: str = "all",   # "all" | "rank" | "class"
    elo_K: int = 0,          # knockout threshold (meaning depends on mode)
) -> dict:
    """
    Run N-round Swiss Elo tournament with optional narrowing.

    3-round fixed schedule:
      R1: all N compete (full Monrad)
      R2: all N compete (full Monrad, re-seeded with R1 Elos)
      R3: narrowed to a band around K (mode-dependent)

    Modes:
      all   → [N, N, N] — no narrowing, full ranking
      rank  → [N, N, b] where b = min(N, K+2)
               R3 competes ranks 1..b; output trimmed to ranks 1..K
      class → [N, N, K] where band = (K-2)..(K+2), capped at N
               R3 competes K items; output trimmed to ranks 1..K

    Caching: the engine owns it. Every pairing is looked up in `cache` first;
    `compare_fn(a, b)` is invoked only on a miss and its result is stored.
    Callers supply a pure judge call and never touch cache keys.

    Invariants:
      - No repeat pairings across all rounds (tracked via frozenset of seen pairs)
      - Same-score artifacts kept adjacent (Monrad pairing)
      - Artifacts eliminated in early rounds are still returned with their final Elo
    """
    past_elos = past_elos or {}
    elo_map: dict[str, ArtifactElo] = {}

    for a in artifacts:
        prior = past_elos.get(a["id"])
        elo_map[a["id"]] = ArtifactElo(
            id=a["id"],
            content_hash=a["content_hash"],
            elo=prior if prior is not None else INITIAL_ELO,
        )

    seen_pairs: set[frozenset] = set()
    round_log = []

    # Band narrowing schedule: [N, N, band_size]
    N_arts = len(artifacts)
    narrowing = _compute_narrowing_schedule(N_arts, n_rounds, elo_mode, elo_K)
    return_band = _compute_return_band(N_arts, elo_mode, elo_K)

    for rnd in range(1, n_rounds + 1):
        # Determine which artifacts are active this round
        n_active = narrowing[rnd - 1]
        current = list(elo_map.values())

        # Narrow: keep only the top n_active by Elo (stable sort by id for ties)
        sorted_all = sorted(current, key=lambda a: (-a.elo, a.id))
        if n_active < len(current):
            active_ids = {a.id for a in sorted_all[:n_active]}
            # Artifacts outside the active set get a bye this round (no comparison)
            initial_byes = [a.id for a in sorted_all[n_active:]]
        else:
            active_ids = {a.id for a in current}
            initial_byes = []
        round_record: dict = {
            "round": rnd,
            "pairs": [],
            "byes": initial_byes,
            "narrowed_to": n_active,
        }

        active_artifacts = [a for a in current if a.id in active_ids]
        pairs = _swiss_pairs(active_artifacts, seen_pairs)

        paired_ids: set[str] = set()

        for a, b in pairs:
            paired_ids.add(a.id)
            paired_ids.add(b.id)

            result = cache.get(task, dims_hash, a.id, a.content_hash,
                               b.id, b.content_hash)
            if result is None:
                result = compare_fn(a, b)
                cache.set(task, dims_hash, a.id, a.content_hash,
                          b.id, b.content_hash, result)
            a_score = float(result.get("a_score", 3.0))
            b_score = float(result.get("b_score", 3.0))
            winner = result.get("winner", "A")

            # Map external "A"/"B"/"draw" labels into each artifact's local "me"/"opp"/"draw".
            a_winner, b_winner = _per_perspective_winners(winner)

            # Record in both artifacts
            a.record(a_score, b.id, b.elo, a_winner, result.get("reason", ""))
            b.record(b_score, a.id, a.elo, b_winner, result.get("reason", ""))

            # Mark this pair as seen so it won't be repeated in future rounds
            seen_pairs.add(frozenset({a.id, b.id}))

            round_record["pairs"].append({
                "a": a.id, "b": b.id,
                "a_score": a_score, "b_score": b_score,
                "winner": winner,
                "a_elo_after": round(a.elo, 1),
                "b_elo_after": round(b.elo, 1),
                "reason": result.get("reason", ""),
            })

        # Handle byes for unpaired active artifacts (narrowing byes are already in round_record["byes"]).
        bye_ids = [a.id for a in active_artifacts if a.id not in paired_ids]
        round_record["byes"].extend(bye_ids)

        round_log.append(round_record)

    # Final ranking by Elo descending
    ranked_ids = [
        a.id for a in sorted(elo_map.values(), key=lambda x: x.elo, reverse=True)
    ]

    # rank_band filters which ranks are returned (narrowing affects competition, not output)
    lo, hi = return_band
    ranked_ids = ranked_ids[lo - 1:hi]

    return {
        "ranked": ranked_ids,
        "artifacts": {aid: elo_map[aid].to_dict() for aid in elo_map},
        "rounds_log": round_log,
        "byes": [r["byes"] for r in round_log],
    }


def _per_perspective_winners(winner: str) -> tuple[str, str]:
    """Translate an external winner label ("A"/"B"/"draw"/else) into the
    per-artifact perspective labels used by ArtifactElo.record().

    Returns (a's_label, b's_label) where each is one of "me"/"opp"/"draw".
    Unknown/non-{A,B} winners (including missing) are treated as draw.
    """
    if winner == "A":
        return "me", "opp"
    if winner == "B":
        return "opp", "me"
    return "draw", "draw"


def _compute_narrowing_schedule(N: int, n_rounds: int, elo_mode: str, elo_K: int) -> list[int]:
    """
    Compute how many artifacts compete in each round.

    Fixed schedule (3-round):
      R1: all N (full Monrad)
      R2: all N (full Monrad, re-seeded with R1 Elos)
      R3: band determined by mode

    Modes:
      all    → [N, N, N]            — no narrowing
      rank   → [N, N, b]            — b = min(N, K+2)
                  R3 competes ranks 1..b; output trimmed to ranks 1..K
      class  → [N, N, b-a+1]        — band = (K-2)..(K+2), capped at N
                  R3 competes that band; output trimmed to ranks 1..K

    Examples:
      N=20, rank K=5:  b=min(20,7)=7  → [20, 20, 7]
      N=20, class K=5:  a=3, b=7      → [20, 20, 5]
      N=4,  class K=5:  a=3, b=4      → [4, 4, 2]   (band capped to N)

    Returns list of int, one per round.
    """
    if elo_mode == "all" or elo_K >= N or n_rounds < 3:
        return [N] * n_rounds

    if elo_mode == "rank":
        # R3 competition: ranks 1..(K+2); output trimmed to ranks 1..K
        return [N, N, min(N, elo_K + 2)]
    # class: R3 competition = band (K-2)..(K+2) capped at N
    a = max(1, elo_K - 2)
    b = min(N, elo_K + 2)
    return [N, N, b - a + 1]  # K when band is interior; ==N when band hits cap


def _compute_return_band(N: int, elo_mode: str, elo_K: int) -> tuple[int, int]:
    """
    Return the (lo, hi) rank band for output trimming after competition.

      rank  → (1, K)    R3 competes 1..(K+2 even), output 1..K
      class → (1, K)    R3 competes K-2..K+2, output 1..K (top K, sorted)
      all   → (1, N)
    """
    if elo_mode == "all" or elo_K >= N:
        return (1, N)

    return (1, elo_K)  # both rank and class output ranks 1..K
