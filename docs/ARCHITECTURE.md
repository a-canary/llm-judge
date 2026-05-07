# Architecture

## Components

```
llm-judge/
├── src/
│   └── cli.js              # Node.js CLI entry point (wrapper)
├── scripts/
│   ├── run_judge.py        # Python CLI: review, gate, elo modes
│   └── test_judge.py       # Test harness with sleep-essay fixtures
├── references/
│   ├── elo.py              # Swiss Elo engine + FIFOCache
│   ├── criteria_template.md # Blank criteria JSON template
│   └── minimax-provider-quirks.md  # Provider-specific notes
└── docs/
    ├── ARCHITECTURE.md     # This file
    └── CLI.md             # Full CLI reference
```

## Provider Abstraction

`call_claude()` in `run_judge.py` dispatches to the configured provider:

| Provider | Transport | Model |
|----------|-----------|-------|
| `cli` (default) | `claude` CLI binary | `--model` arg |
| `minimax` | `urllib` POST to `https://api.minimax.io/v1/chat/completions` | `--model` arg |
| `<URL>` | `urllib` POST to arbitrary OpenAI-compatible endpoint | `--model` arg |

## Cache Flow

```
compare_fn(task, dims_hash, a_elo, b_elo, cache)
    │
    ├─► cache.get(key)  ──► hit? return cached result
    │
    └─► cache.miss:
            call_claude(pairwise_prompt)
                │
                ▼
            parse_pairwise_result(raw_text)
                │
                ▼
            cache.set(key, result)
                │
                ▼
            return result

Cache key: sha256(f"{task}:{dims_hash}:{sorted_pair}:{hashes[:8]}")
  - sorted_pair: (A,B) always sorted so (A,B) and (B,A) collide
  - hashes: first 8 chars of content hash for each artifact
```

FIFO eviction: when `len(cache) > 512`, oldest entry is removed. Cache persists at `~/.cache/llm-judge/fifo_cache.json`.

## Elo Engine (`references/elo.py`)

### FIFOCache
- `get(task, dims_hash, a_id, a_hash, b_id, b_hash)` → `dict | None`
- `set(...)` → stores result, evicts oldest if over capacity
- `stats()` → `{"cached": N, "max": 512}`

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
all:   [N, N, N]    — full competition every round
rank:  [N, N, K+2]  — R3 competes ranks 1..K+2, output 1..K
class: [N, N, K]    — R3 competes ranks K-2..K+2, output 1..K
```

## Error Handling

| Situation | Behavior |
|-----------|----------|
| HTTP error / timeout | Print error, return `(5.0, 5.0)` (draw) |
| JSON parse failure | Fall back to regex: `Winner: A/B` + score extraction |
| MiniMax ` op ` thinking blocks | Strip with regex before JSON parse |
| Cache miss | Call judge, cache result |
| Cache hit | Return cached result silently |
| Empty artifact | Return error in result dict |
