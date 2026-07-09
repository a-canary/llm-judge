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

- `test/` — Node.js smoke fixtures (`test/fixtures/*.md`) consumed by the CLI smoke scripts in `package.json` (`npm test`, `npm run test:elo`, `npm run test:gate`). Not a unit-test tree.
- `tests/` — pytest unit tests for the Python library code (`scripts/run_judge.py`, `references/elo.py`). Discovered by pytest from its default naming convention.

```bash
# Node.js CLI smoke (requires LLM API key)
npm test
npm run test:elo
npm run test:gate

# Python unit tests (no live LLM calls)
pytest
```

## File an Issue

Open an issue at https://github.com/a-canary/llm-judge/issues.
PRs welcome — issues and PRs may be triaged slowly (solo dev).