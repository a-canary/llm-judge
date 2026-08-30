# Architecture

## Components

```
llm-judge/
├── src/
│   └── cli.js              # Node.js CLI entry point (thin Python spawner)
├── scripts/
│   ├── run_judge.py        # Python CLI: review, gate, elo modes
│   └── test_judge.py       # Test harness with sleep-essay fixtures
├── references/
│   ├── __init__.py         # Package marker
│   ├── artifacts.py        # Artifact loading: files, inline text, URLs
│   ├── caller.py           # LLM invocation: claude CLI + OpenAI-compat API
│   ├── criteria.py         # Default criteria definitions + validation
│   ├── elo.py              # Swiss Elo engine + FIFOCache
│   ├── parsers.py          # Result parsers: pairwise, gate, review
│   ├── prompts.py          # Prompt builders: pairwise, critique, gate
│   ├── providers.py        # Cross-platform credential lookup
│   └── criteria_template.md # Blank criteria JSON template
└── docs/
    ├── ARCHITECTURE.md     # This file
    └── CLI.md             # Full CLI reference
```

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `artifacts.py` | Load artifacts from file paths, inline:`TEXT`, or URLs; return normalized dict with id, content, content_hash
| `caller.py` | Invoke LLM via `claude` CLI binary or OpenAI-compatible HTTP POST; returns raw text response
| `criteria.py` | Default 5-dimension criteria (Correctness 30%, Completeness 25%, Clarity 20%, Maintainability 15%, EdgeCases 10%) + `validate_criteria()`
| `parsers.py` | Parse raw LLM output into structured dicts; strip `<thinking>` blocks before JSON parse; fall back to regex
| `prompts.py` | Build prompt strings for pairwise comparison, critique review, and gate evaluation

## Provider Abstraction

`call_claude()` in `caller.py` dispatches to the configured provider:

| Provider | Transport | Model |
|----------|-----------|-------|
| `cli` (default) | `claude` CLI binary | `--model` arg |
| `<URL>` | `urllib` POST to arbitrary OpenAI-compatible endpoint (e.g. `https://api.minimax.io/v1`) | `--model` arg |

## Cache Flow

The **engine owns the cache**. `rank_swiss_elo` looks up every pairing itself and calls `compare_fn(a, b)` only on a miss, then stores the result.
Callers supply a pure judge call and never construct cache keys.

```
rank_swiss_elo  (references/elo.py)
    |
    +-- cache.get(task, dims_hash, a.id, a.content_hash, b.id, b.content_hash)
    |       `-- hit? use it, no LLM call
    |
    `-- miss:
            compare_fn(a, b)          # supplied by the caller - pure judge call
                |
                +- prompts.build_pairwise_prompt(a, b, dimensions, task)
                +- caller.call_claude(prompt, model, effort, provider)
                `- parsers.parse_pairwise_result(raw_text)
                |
                v
            cache.set(..., result)

Cache key: sha256(f"v2:{task}:{dims_hash}:{sorted_pair}")
  - sorted_pair: (A,B) always sorted so (A,B) and (B,A) collide
  - pair segment embeds first 8 chars of each artifact's content hash
  - "v2:" prefix retires pre-v2 entries, which stored win/draw flags but no
    "winner" key and so were silently scored as A-wins on every cache hit
```

FIFO eviction: when the cache exceeds 512 entries, the oldest is removed.
Cache persists at `~/.cache/llm-judge/fifo_cache.json` by default; `FIFOCache(path=...)` overrides the backing file per instance (no module-global patching).

## Elo Engine (`references/elo.py`)

### FIFOCache
- `FIFOCache(max_size=512, path=None)` - `path` defaults to `CACHE_PATH`; pass one to isolate the backing file
- `get(task, dims_hash, a_id, a_hash, b_id, b_hash)` → `dict | None`
- `set(...)` → stores result, evicts oldest if over capacity
- `stats()` → `{"cached": N, "max": 512}`

### compare_fn contract
`compare_fn(a: ArtifactElo, b: ArtifactElo)` returns a `dict` with keys `a_score`, `b_score`, `winner` (`"A"`/`"B"`/anything else = draw), `reason`.
Invoked only on a cache miss; it must not do its own caching.

`winner` names a **slot, not an artifact id**: `"A"` means the first argument won, `"B"` the second. Which artifact lands in which slot is decided by `_swiss_pairs` (Elo desc, then id asc), not by the caller.
A missing `winner` is scored a draw — an earlier `"A"` default is what made every pre-v2 cache hit an A-win.

### ArtifactElo
```python
@dataclass
class ArtifactElo:
    id: str
    content_hash: str
    elo: float = 1500.0
    matches: list[dict] = field(default_factory=list)

    def record(self, my_score: float, opponent_id: str, opponent_elo: float,
               winner: str, reason: str) -> None:
        expected = 1.0 / (1.0 + 10 ** ((opponent_elo - self.elo) / 400.0))
        actual = 1.0 if winner == "me" else 0.0 if winner == "opp" else 0.5
        self.elo = self.elo + 32 * (actual - expected)
```

### Swiss Pairing (`_swiss_pairs`)
1. Sort by (Elo desc, id asc) — stable tiebreaking
2. Attempt adjacent pairs: (0,1), (2,3), ...
3. For each proposed pair: if already seen in prior round, swap B with next unpaired artifact
4. If no novel partner exists, first artifact gets a bye

### Narrowing Schedule
```
all:  [N, N, N]        — full competition every round
rank: [N, N, K+2]      — R3 competes ranks 1..K+2, output 1..K
                           Best for EA: keep top K after breeding
                           (e.g. --elo-rank 8 with pop=16 → keep top 50%)
class:[N, N, K]        — R3 competes ranks K-2..K+2, output 1..K (unsorted)
                           Best for EA: select survivors without full sort
                           (e.g. --elo-class 4 with pop=16 → 4 unsorted survivors)
```

## Error Handling

| Situation | Behavior |
|-----------|----------|
| HTTP error / timeout | Print error, return `(5.0, 5.0)` (draw) |
| JSON parse failure | Fall back to regex: `Winner: A/B` + score extraction |
| MiniMax ` op ` thinking blocks | Strip with regex before JSON parse |
| Cache miss | Engine calls `compare_fn`, caches the result |
| Cache hit | Engine returns the cached result; `compare_fn` is never called |
| Empty artifact | Return error in result dict |
