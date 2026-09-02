# CHOICES.md — llm-judge

## Mission

USR-MSN-0003 (LLM democratization) — expose evaluation infrastructure that makes rigorous
artifact quality judgment accessible without proprietary tooling. Secondary: USR-MSN-0001
(trading) via EA fitness-function selection; USR-MSN-0002 (OneNation) via pass/gate checks
on generated documents.

---

## Scope

Build and maintain a CLI tool that evaluates artifacts with LLMs via three modes:
`review`, `gate`, and `elo`. Publishable as open-source. No web server, no daemon.

**In scope:**
- Three evaluation modes: review, gate, elo (Swiss Monrad)
- Artifact sources: file, URL, inline text
- Provider abstraction: claude CLI + any OpenAI-compatible base URL
- Cross-platform credential lookup: LLM_JUDGE_API_KEY env > keyring > pass
- Configurable criteria dimensions with weight validation
- Persistent FIFO cache at ~/.cache/llm-judge/ (prevents duplicate LLM calls)
- Elo narrowing modes: --elo-rank K (sorted top-K) and --elo-class K (pivot survivor)
- Python CLI (scripts/run_judge.py) as canonical implementation
- Node.js thin wrapper (src/cli.js) delegating to Python
- Pipeliner module (`pipeliner/llm_judge_module.ts`) for typed integration

**Out of scope (requires Director approval to add):**
- Server/daemon mode or REST API
- Database persistence (Postgres, SQLite) — FIFO JSON cache is sufficient
- Web UI or dashboard
- Async/concurrent LLM calls (sequential is intentional — rate-limit safety)
- Multi-model consensus (single-judge per call)
- Automatic benchmark versioning (V1/V2/V3/V4 — historical, no longer shipped; see git history)

---

## Architecture

### Language
- Canonical: Python 3.9+ (scripts/run_judge.py + references/elo.py)
- Wrapper: Node.js 18+ (src/cli.js) — thin passthrough only, no logic
- Pipeliner integration: TypeScript (pipeliner/llm_judge_module.ts)

### Dependency policy
- Zero heavy dependencies — stdlib + optional `keyring` for credential lookup
- No `requests` — use `urllib` only
- No `openai` SDK — raw HTTP POST to /chat/completions

### File layout
```
scripts/run_judge.py   # CLI entry: review, gate, elo dispatch + all prompt builders
references/elo.py      # Pure engine: FIFOCache, ArtifactElo, rank_swiss_elo
references/criteria_template.md
src/cli.js             # Node thin wrapper
test/fixtures/         # Static essay fixtures (no live LLM calls)
tests/                 # pytest unit tests (no live LLM calls)
scripts/test_judge.py  # Integration test harness (live LLM, slow)
pipeliner/             # defineModule + test suite for pipeliner integration
docs/                  # Architecture + CLI reference
```

### Hermes skill
- Repo-local `SKILL_reference.md` was trashed in #5 (2d60732); per the trash commit it referenced a stale provider. The skill canonical location is `arc-skills/skills/llm-judge/` (verify before depending on the path — see evidence in 2d60732).

### Elo algorithm
- 3-round Swiss Monrad (fixed schedule)
- K-factor = 32, initial Elo = 1500
- Narrowing schedule: one inclusive rank band (lo, hi) per round; R3's band is mode-dependent
- `class` mode races the band straddling the cut (K-2..K+2), `rank` mode re-races the leaders (1..K+2)
- No repeat pairings via frozenset tracking
- Cache key: sha256(task + dims_hash + sorted_pair + content_hashes[:8])

### Credential precedence (immutable)
1. LLM_JUDGE_API_KEY env var
2. keyring service="llm-judge", key="<host>://api_key"
3. pass show <host>/api-key

### Output format
- review/gate: Markdown (stdout + optional --output file)
- elo: Markdown table with Elo scores + rounds log

---

## Technology Choices

| Concern | Choice | Reason |
|---------|--------|--------|
| Language | Python 3.9+ | Widest install base; no compile step |
| HTTP client | urllib (stdlib) | Zero deps; sufficient for OpenAI-compat APIs |
| Credentials | keyring + pass fallback | Cross-platform; pipeline-safe via env var |
| Cache | OrderedDict FIFO JSON | Simple, portable, no DB required |
| Test fixtures | Static markdown files | Deterministic; no LLM call for unit tests |
| Node wrapper | Thin spawn passthrough | npm install UX without duplicating logic |
| Pipeliner | defineModule + child_process spawn | Keeps Python canonical; typed I/O at boundary |

---

## Quality Gates

- All criteria weights must sum to 1.0 (validated at runtime, hard error)
- Cache key must be symmetric: (A,B) and (B,A) produce identical keys
- Narrowing must never eliminate more artifacts than requested (K <= N invariant)
- Elo seeding and band narrowing must use the same (Elo desc, id asc) tiebreak
- `--elo-class K` must compete strictly fewer artifacts than `--elo-rank K` (that is its only reason to exist)
- parse_pairwise_result must fall back to regex when JSON parse fails (no hard crash)
- The gate reads exactly ONE decision site — the first verdict-labelled line, else a lone verdict word on its own line — and never scans the document for an affirmative-looking token; a scan lets a FAIL verdict be overridden by "pass" appearing later in the rationale
- The gate fails CLOSED: no decision site and no score over the bar means blocked
- Fail-closed must not become fail-always: decorated approvals (`**PASS**`, `Result: PASSED`) still pass, or the gate blocks good artifacts
- A gate verdict with no parseable score reports `scored: False` and renders `--`, never a fabricated `0.00/5`
- Every parser strips reasoning scratchpad before parsing — `<thinking>`/`<think>`, any case — so a verdict is never read out of deliberation
- Only CLOSED scratchpad blocks are stripped, each paired with its innermost open: an unclosed tag is a mention inside a payload (`"verdict": "no <think> needed"`), and spanning to a later block's closing tag would destroy valid output
- Unparseable review output degrades to raw text (`parsed: False`), never to fabricated scores — including JSON that parses but lacks the fields the caller renders
- `--provider` that is neither `cli` nor a URL must raise, never resolve to an empty base URL — validated in `main()` before any artifact loads or API call, surfaced as a message not a traceback
- `--elo-rank` / `--elo-class` must be placed AFTER artifact paths (argparse nargs='*' greedy)
- Pipeliner module test suite must run without live LLM (mocked spawn)
- Node shim must NOT override cwd — artifact paths are relative to the user's shell
- `npm test` runs the offline pytest suite; live-LLM runs are `npm run demo:*`
- Unit tests import from the owning `references/*` module, never re-exported via `run_judge`

---

## Status (2026-05-14)

- Phase 0 (foundation): complete
- Phase 1 (correctness/robustness): complete — all 5 deliverables shipped (0f29c54, f697ffc)
- Phase 2 N-0001 (pipeliner module structure): complete — db2d951
- Phase 2 EA integration: deferred (lives in trading project, not here)
- Phase 3 (cc publish): next slice — ship installable plugin manifest
