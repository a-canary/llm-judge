# CLI Reference

## Synopsis

```
llm-judge <mode> [options] -- <artifact> [<artifact> ...]
```

## Modes

### `review`

Produces a detailed qualitative critique of each artifact, evaluated against the prompt and criteria.

```bash
llm-judge review --prompt "Is this a clear technical memo?" memo.md notes.md
```

Output: Markdown document with a section per artifact, covering each criteria dimension with a score and explanation.

### `gate`

Produces a pass/fail verdict for each artifact. Suitable for PRs, releases, and acceptance criteria.

```bash
llm-judge gate --prompt "Does this proposal meet safety requirements?" proposal.md
```

Output: Markdown table with pass/fail icon, score out of 5, and a one-line verdict. Bottom line: overall PASS or FAIL.

### `elo`

Runs a Swiss Elo tournament across all artifacts, ranking them by comparative quality.

```bash
# Full ranking (all artifacts compete all 3 rounds)
llm-judge elo --prompt "Which implementation is most idiomatic Go?" a.go b.go c.go d.go

# Sorted top-K: narrows R3 to ranks 1..K+2
llm-judge elo --elo-rank 3 --prompt "Find the top 3 essays" *.md

# Class K: narrows R3 to ranks K-2..K+2 (good for finding middle tier)
llm-judge elo --elo-class 5 --prompt "Rank the middle tier" *.md
```

Output: Markdown table with final Elo rating and match count per artifact, plus a per-round log showing pairings and reasons.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--prompt TEXT` | Task framing what "good" means (required) | — |
| `--model MODEL` | Model name | `claude-sonnet-4-6` |
| `--provider NAME` | `cli`, `minimax`, or URL | `cli` |
| `--effort LEVEL` | Claude effort (`low`, `medium`, `high`) | `high` |
| `--criteria FILE` | Path to criteria JSON file | built-in generic |
| `--criteria-text JSON` | Inline criteria as JSON string | built-in generic |
| `--elo-rank K` | (elo) Sorted top-K: R3 competes ranks 1..K+2, eliminates rest | — |
| `--elo-class K` | (elo) Pivot top-K: competes ranks K-2..K+2 — returns top K unsorted. Best for EA selection when you only need to eliminate the bottom N-K | — |
| `--rounds N` | (elo) Number of Swiss rounds | `3` |
| `--output FILE` | Write output to file | stdout |

## Arguments

### Artifact Specifiers

Artifacts can be specified as:

| Form | Example | Behavior |
|------|---------|----------|
| File path | `./memo.md` | Read file contents in full |
| Inline text | `inline:your text here` | Use text directly |
| URL | `https://example.com/text` | Fetch and use content |

> **Note:** File paths are read in full. For large artifacts (>100KB), truncate before passing: `head -c 50000 large.md > tmp.md && llm-judge review ... tmp.md`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (results printed) |
| 1 | Parse error or unexpected failure |

## Examples

```bash
# Review with custom criteria
llm-judge review \
  --criteria ./legal-criteria.json \
  --prompt "Does this contract meet regulatory standards?" \
  contract_v1.md contract_v2.md

# Gate with minimax provider
llm-judge gate \
  --provider minimax \
  --model MiniMax-M2.7 \
  --prompt "Is this code safe to merge?" \
  pr_1234.md

# Elo with narrowed top-K (best for EA — keep top K after breeding)
# --elo-rank 8 with pop=16 keeps top 50%
llm-judge elo \
  --elo-rank 8 \
  --rounds 3 \
  --prompt "Rank the top candidates" \
  artifacts/*.md

# Elo with custom model via arbitrary OpenAI-compatible URL
llm-judge elo \
  --provider https://api.example.com/v1 \
  --model my-finetuned-model \
  --prompt "Which response best follows the style guide?" \
  responses/*.md
```

## Common Pitfalls

- **`--elo-rank`/`--elo-class` ordering:** Must come AFTER artifact paths. The argparse `nargs='*'` is greedy — it consumes all positional-like arguments before flags are parsed.
  - Correct: `llm-judge elo a.md b.md --prompt "?" --elo-rank 2`
  - Wrong: `llm-judge elo --elo-rank 2 a.md b.md --prompt "?"`

- **Narrowing with small N:** With N ≤ 10, narrowing eliminates artifacts after only 1-2 comparisons. Rankings may diverge significantly from a full run. Only use narrowing for N ≥ 20.

- **Cache persistence:** The FIFO cache at `~/.cache/llm-judge/fifo_cache.json` persists across runs. Sequential calls with identical artifacts + prompt will return cached results. Clear the cache file to force re-evaluation.
