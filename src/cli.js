#!/usr/bin/env node
/**
 * llm-judge CLI wrapper — Node.js entry point that delegates to the Python core.
 *
 * Discovery order for the Python interpreter:
 * 1. ${SCRIPT_DIR}/../venv/bin/python3  (pip install -e . in a venv)
 * 2. python3 in PATH
 *
 * The Python script (scripts/run_judge.py) is invoked with all args passed through.
 * All logic lives in Python; this is purely a discovery/shim layer.
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const SCRIPT_DIR = path.dirname(__dirname);   // e.g. /path/to/llm-judge/src
const REPO_ROOT = path.join(SCRIPT_DIR, '..');
const PY_SCRIPT = path.join(SCRIPT_DIR, 'scripts', 'run_judge.py');

function findPython() {
  // Check for a local venv first
  const venvPython = path.join(REPO_ROOT, 'venv', 'bin', 'python3');
  if (fs.existsSync(venvPython)) return venvPython;
  // Fall back to whatever Python is on PATH
  return 'python3';
}

const argv = process.argv.slice(2);

if (!fs.existsSync(PY_SCRIPT)) {
  console.error('Error: scripts/run_judge.py not found. Is llm-judge installed?');
  console.error('  pip install -e .   # from repo root, or create a venv first');
  process.exit(1);
}

const python = findPython();
const child = spawn(python, [PY_SCRIPT, ...argv], {
  stdio: 'inherit',
  cwd: REPO_ROOT,
  env: { ...process.env },
});
child.on('exit', code => process.exit(code));
child.on('error', err => {
  console.error(err);
  process.exit(1);
});