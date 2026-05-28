#!/usr/bin/env bash
# llm-judge quick-start: review two artifacts and critique each.
#
# Prerequisites:
#   python3 -m venv venv && venv/bin/pip install -e .
#   npm install -g .   # optional, for: llm-judge
#
# Required env vars (pipeline-friendly):
#   LLM_JUDGE_API_KEY     — your API key
#   LLM_JUDGE_API_BASE    — base URL, e.g. https://api.minimax.io/v1
#   LLM_JUDGE_MODEL       — model name, e.g. MiniMax-M2  [default: MiniMax-M2]
#
# Alternatively, use provider-specific vars:
#   MINIMAX_API_KEY + MINIMAX_API_BASE will be used if LLM_JUDGE_* vars are absent.
#
# Usage:
#   bash examples/run_review.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# --- Credential resolution (pipeline-friendly) ---
if [[ -z "${LLM_JUDGE_API_KEY:-}" ]]; then
  if [[ -n "${MINIMAX_API_KEY:-}" ]]; then
    export LLM_JUDGE_API_KEY="$MINIMAX_API_KEY"
    export LLM_JUDGE_API_BASE="${MINIMAX_API_BASE:-https://api.minimax.io/v1}"
  else
    echo "Error: LLM_JUDGE_API_KEY is not set." >&2
    echo "  export LLM_JUDGE_API_KEY=your_key" >&2
    echo "  export LLM_JUDGE_API_BASE=https://api.minimax.io/v1" >&2
    exit 1
  fi
fi

API_BASE="${LLM_JUDGE_API_BASE:-https://api.minimax.io/v1}"
MODEL="${LLM_JUDGE_MODEL:-MiniMax-M2}"
PYTHON="${REPO_DIR}/venv/bin/python3"

# Fallback: use python3 from PATH if no venv
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

A="${REPO_DIR}/test/fixtures/essay_a.md"
B="${REPO_DIR}/test/fixtures/essay_b.md"

echo "=== Review Mode ===" >&2
"$PYTHON" "${REPO_DIR}/scripts/run_judge.py" \
  review \
  "$A" "$B" \
  --prompt "Which essay is more informative and well-written?" \
  --model "$MODEL" \
  --provider "$API_BASE" \
  2>&1