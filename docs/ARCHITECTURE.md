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
| `parsers.py` | Parse raw LLM output into structured dicts. `strip_thinking()` runs first in every parser — a verdict must never be read out of a reasoning model's scratchpad. `pairwise`/`gate` fall back to regex (the gate's fallback fails closed); `review` degrades to raw text (`parsed: False`) rather than inventing scores
| `prompts.py` | Build prompt strings for pairwise comparison, critique review, and gate evaluation
| `providers.py` | Resolve API base URL and look up the API key (env, then keyring, then pass). `resolve_api_url()` raises `ValueError` on a provider that is neither `cli` nor a URL
| `elo.py` | Swiss Elo tournament engine and persistent FIFO comparison cache

## Provider Abstraction

`call_claude()` in `caller.py` dispatches to the configured provider:

| Provider | Transport | Model |
|----------|-----------|-------|
| `cli` (default) | `claude` CLI binary | `--model` arg |
| `<URL>` | `urllib` POST to arbitrary OpenAI-compatible endpoint (e.g. `https://api.minimax.io/v1`) | `--model` arg |

## Cache Flow

```
compare_fn(task, dims_hash, a_elo, b_elo, cache)
    │
    ├─► cache.get(key)  ──► hit? return cached result
    │
    └─► cache.miss:
            prompts.build_pairwise_prompt(a, b, dimensions, task)
                │
                ▼
            caller.call_claude(prompt, model, effort, provider)
                │
                ▼
            parsers.parse_pairwise_result(raw_text)
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
    content: str = ""      # carried so compare_fn needs no id-to-content side-table
    elo: float = 1500.0
    matches: list[dict] = field(default_factory=list)

    def record(self, my_score: float, opponent_id: str, opponent_elo: float,
               winner: str, reason: str) -> None:
        expected = 1.0 / (1.0 + 10 ** ((opponent_elo - self.elo) / 400.0))
        actual = 1.0 if winner == "me" else 0.0 if winner == "opp" else 0.5
        self.elo = self.elo + 32 * (actual - expected)
```

### Swiss Pairing (`_swiss_pairs`)
1. Sort by (Elo desc, id asc) — stable tiebreaking (shared with band narrowing)
2. Attempt adjacent pairs: (0,1), (2,3), ...
3. For each proposed pair: if already seen in prior round, swap B with next unpaired artifact
4. If no novel partner exists, first artifact gets a bye

### Narrowing Schedule
Each round is scheduled as an inclusive 1-based **rank band** — the ranks that
compete that round — not a bare count. A count could only ever mean "the top N",
which cannot express `class` mode's band around the cut.

```
all:  [(1,N), (1,N), (1,N)]        — full competition every round
rank: [(1,N), (1,N), (1,K+2)]      — R3 re-races ranks 1..K+2, output 1..K
                                       Best for EA: keep top K after breeding
                                       (e.g. --elo-rank 8 with pop=16 → top 50%)
class:[(1,N), (1,N), (K-2,K+2)]    — R3 races only the band straddling the cut,
                                       output 1..K (by Elo)
                                       Best for EA: cheapest survivor cut
                                       (e.g. --elo-class 4 with pop=16 → 4 survivors)
```

Artifacts outside the round's band take a bye and keep their current Elo.
`competing_band(N, mode, K)` is the single source of truth for the R3 band; the
CLI header derives its "R3 competes a..b" line from it rather than recomputing.

## Error Handling

| Situation | Behavior |
|-----------|----------|
| HTTP error / timeout | Print error, return `(5.0, 5.0)` (draw) |
| JSON parse failure | Fall back to regex: `Winner: A/B` + score extraction |
| Reasoning scratchpad (`<thinking>`, `<think>`) | `strip_thinking()` in every parser, before both the JSON and the regex path; case-insensitive, depth-matched so nested blocks collapse, balanced blocks only so a payload mention never spans to a later block |
| Gate output with no affirmative verdict | Fails CLOSED (`passed: False`) — a refusal, not an approval. `_gate_decision` reads every decision site and any rejection dominates; fenced examples and hedged approvals do not vote |
| Gate verdict with no parseable score | `scored: False`; the CLI renders `--` rather than a fabricated `0.00/5` |
| Unknown `--provider` value | `ValueError` naming the bad value; caught in `main()` → `error: …` + exit 1, before artifacts load |
| Unparseable review prose, or JSON missing `scores`/`average` | `parsed: False` + raw text echoed; no fabricated scores |
| Cache miss | Call judge, cache result |
| Cache hit | Return cached result silently |
| Empty artifact | Return error in result dict |
