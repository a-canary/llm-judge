# Contributing to LLM Judge

## Dev Setup

```bash
git clone https://github.com/a-canary/llm-judge.git
cd llm-judge

# Node.js CLI
npm install -g .

# Python CLI
pip install -e .
```

## Run Tests

Two test directories, by language:

- `test/` — shared markdown fixtures (`test/fixtures/*.md`) consumed by the live-LLM demo scripts in `package.json` (`npm run demo:review`, `demo:elo`, `demo:gate`). Not a unit-test tree.
- `tests/` — pytest unit tests for the Python library code (`scripts/run_judge.py`, `references/elo.py`). Discovered by pytest from its default naming convention.

```bash
# Unit tests — no live LLM calls (this is what CI runs)
npm test          # alias for the line below
pytest

# Live-LLM demos against test/fixtures/ (costs real API calls)
npm run demo:review
npm run demo:elo
npm run demo:gate
```

## File an Issue

Open an issue at https://github.com/a-canary/llm-judge/issues.
PRs welcome — issues and PRs may be triaged slowly (solo dev).