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

```bash
# Node.js tests
node src/cli.js review --prompt 'Which essay is more informative?' test/fixtures/essay_a.md test/fixtures/essay_b.md
node src/cli.js elo --prompt 'Which is more clearly written?' test/fixtures/essay_a.md test/fixtures/essay_b.md
node src/cli.js gate --prompt 'Does this essay meet the quality bar?' test/fixtures/essay_a.md

# Python tests
pytest
```

## File an Issue

Open an issue at https://github.com/a-canary/llm-judge/issues.
PRs welcome — issues and PRs may be triaged slowly (solo dev).