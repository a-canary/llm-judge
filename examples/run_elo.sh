#!/usr/bin/env bash
# llm-judge Elo tournament: Swiss-style ranking across two artifacts.
#
# Prerequisites:
#   python3 -m venv venv && venv/bin/pip install -e .
#
# Required env vars:
#   LLM_JUDGE_API_KEY / MINIMAX_API_KEY
#   LLM_JUDGE_API_BASE / MINIMAX_API_BASE
#
# Usage:
#   bash examples/run_elo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# --- Credential resolution ---
if [[ -z "${LLM_JUDGE_API_KEY:-}" ]]; then
  if [[ -n "${MINIMAX_API_KEY:-}" ]]; then
    export LLM_JUDGE_API_KEY="$MINIMAX_API_KEY"
    export LLM_JUDGE_API_BASE="${MINIMAX_API_BASE:-https://api.minimax.io/v1}"
  else
    echo "Error: LLM_JUDGE_API_KEY is not set." >&2
    exit 1
  fi
fi

API_BASE="${LLM_JUDGE_API_BASE:-https://api.minimax.io/v1}"
MODEL="${LLM_JUDGE_MODEL:-MiniMax-M2}"
PYTHON="${REPO_DIR}/venv/bin/python3"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

A="${REPO_DIR}/test/fixtures/essay_a.md"
B="${REPO_DIR}/test/fixtures/essay_b.md"

echo "=== Elo Mode (Swiss tournament) ===" >&2
"$PYTHON" "${REPO_DIR}/scripts/run_judge.py" \
  elo \
  "$A" "$B" \
  --prompt "Which essay is more clearly written and informative?" \
  --model "$MODEL" \
  --provider "$API_BASE" \
  2>&1