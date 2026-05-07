# LLM Judge

> **CLI tool for evaluating artifacts with LLMs** — Swiss Elo ranking, pass/gate, and qualitative review.

LLM Judge uses a configured LLM (Claude, GPT, or any OpenAI-compatible API) to evaluate, compare, and rank artifacts. It supports three evaluation modes: qualitative critique (`review`), pass/fail gating (`gate`), and pairwise Swiss Elo ranking (`elo`). Artifacts can be file paths, inline text, or URLs.

## Install

```bash
# Clone
git clone https://github.com/a-canary/llm-judge.git
cd llm-judge

# Python CLI (pip)
pip install -e .
llm-judge --help

# Node.js CLI (npm)
npm install -g .
llm-judge --help
```

## Quick Start

```bash
# Review: qualitative critique of each artifact
llm-judge review --prompt "Is this a clear technical memo?" memo.md notes.md

# Gate: pass/fail for each artifact
llm-judge gate --prompt "Does this proposal meet safety requirements?" proposal.md

# Elo: Swiss-ranked tournament across all artifacts
llm-judge elo --prompt "Which implementation is most idiomatic Go?" a.go b.go c.go d.go

# Elo: sorted top-K (narrows R3 competition to ranks 1..K+2)
llm-judge elo --elo-rank 3 --prompt "Find the top 3 essays" *.md

# Elo: keep top K (narrows R3 to ranks 1..K+2, eliminates rest)
# Best for EA: keep top 50% after breeding — e.g. K=8 when pop=16
llm-judge elo --elo-rank 8 --prompt "Which essays have the strongest arguments?" *.md

# Elo: pivot top K (narrows R3 to ranks K-2..K+2, returns top K unsorted)
# Best for EA: select survivors without full sort — e.g. K=4 with pop=16 keeps 4 without ranking 1-4
llm-judge elo --elo-class 4 --prompt "Select survivors without full sort" *.md
```

## CLI Reference

```
llm-judge <mode> [options] -- <artifact> [<artifact> ...]

Modes:
  review    Detailed qualitative critique of each artifact
  gate     Pass/fail assessment per artifact
  elo      Swiss Elo tournament — 3 rounds of pairwise comparisons

Options:
  --prompt TEXT       Task framing what "good" means (required)
  --model MODEL      Model name [default: claude-sonnet-4-6]
  --provider NAME    Provider: cli, minimax, or OpenAI-compatible URL [default: cli]
  --effort LEVEL    Claude effort setting [default: high]
  --criteria FILE    Path to criteria JSON file [default: built-in generic]
  --criteria-text JSON  Inline criteria JSON string
  --elo-rank K       (elo) Sorted top-K: R3 competes ranks 1..K+2
  --elo-class K      (elo) Roughly-sorted class: R3 competes ranks K-2..K+2
  --rounds N         (elo) Number of Swiss rounds [default: 3]
  --output FILE      Write results to file [default: stdout]
  -h, --help        Show this help
```

### Provider Configuration

| Provider | Config | Notes |
|----------|--------|-------|
| `cli` (default) | Claude CLI in PATH | Uses `claude-sonnet-4-6` by default |
| `minimax` | API key at `pass show minimax/api-key` | API base: `https://api.minimax.io/v1` |
| Arbitrary URL | Any OpenAI-compatible endpoint | Pass full URL as `--provider` |

### Criteria Dimensions

The judge evaluates across configurable **dimensions**. Each dimension has:
- `name` — short label (e.g. "Correctness")
- `weight` — importance fraction (must sum to 1.0)
- `desc` — what "good" means for this dimension

**Built-in generic criteria** (fallback):

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Correctness | 30% | Does it do what it claims? No factual or logical errors? |
| Completeness | 25% | All parts of the task addressed? Edge cases handled? |
| Clarity | 20% | Intent obvious? Structure logical? No ambiguous terms? |
| Maintainability | 15% | Well-organized? No unnecessary complexity? |
| EdgeCases | 10% | Failure modes addressed? Errors handled gracefully? |

**Domain-specific example (legal documents):**
```json
[{"name":"LegalSoundness","weight":0.35,"desc":"Arguments are legally valid and jurisdiction-appropriate"},
 {"name":"Clarity","weight":0.20,"desc":"Language is unambiguous, defined terms used correctly"},
 {"name":"Completeness","weight":0.20,"desc":"All material terms and conditions are present"},
 {"name":"Persuasiveness","weight":0.25,"desc":"Arguments are compelling to a neutral arbiter"}]
```

## Architecture

```
Artifact(s)
    │
    ▼
run_judge.py (CLI entry point)
    │
    ├── review mode ──► call_claude() ──► build_critique_prompt() ──► Claude ──► Markdown report
    │
    ├── gate mode  ──► call_claude() ──► build_gate_prompt()    ──► Claude ──► pass/fail table
    │
    └── elo mode
            │
            ▼
        rank_swiss_elo()  ◄── compare_fn()
            │                    │
            │              call_claude()
            │              build_pairwise_prompt()
            │                    │
            │                    ▼
            │              Claude ──► parse_pairwise_result()
            │                    │
            ▼                    ▼
        elo.py ───────────► FIFOCache (~/.cache/llm-judge/fifo_cache.json)
```

### Elo Algorithm

Three-round Swiss (Monrad) tournament:
1. **Seed (R0):** All artifacts start at Elo 1500. Prior Elos are reused if available.
2. **R1 + R2:** Full Monrad — sort by Elo, pair adjacent. Repeat-swap to avoid repeat pairings.
3. **R3:** Narrowed band (if `--elo-rank K` or `--elo-class K`). Full ranking otherwise.

Elo update: `new = old + 32 × (actual − expected)`, where `expected = 1 / (1 + 10^((opp−mine)/400))`.

### Cache

Never asks the judge the same question twice. Cache key:
```
sha256(task + dims_hash + sorted_pair + content_hashes[:8])
```
Stored at `~/.cache/llm-judge/fifo_cache.json`, FIFO eviction at 512 entries.

## Output Examples

**Elo ranking:**
```
## Final Ranking
| Rank | Artifact       | Elo    | Matches |
|------|----------------|--------|---------|
| 1    | essay_d.md     | 1632.1 | 3       |
| 2    | essay_a.md     | 1584.7 | 3       |
| 3    | essay_c.md     | 1467.3 | 3       |
```

**Gate:**
```
✅ essay_a.md — 4.2/5 — Meets bar
❌ essay_b.md — 2.8/5 — Below bar, major gaps
FAIL ❌
```

## Hermes Skill Version

This is the standalone open-source version. The **Hermes Agent skill** (`llm-judge` in the `productivity/` skill directory) includes additional documentation on:
- Multi-version benchmark design (V1/V2/V3/V4 pattern)
- Behavioral sycophancy evaluation rubric
- Known HBR findings to encode in benchmarks
- Integration with EA/evolutionary runs

If you are running LLM Judge as a Hermes Agent tool, use the skill version for the full documentation.

## License

MIT
