#!/usr/bin/env node
/**
 * llm-judge CLI wrapper
 * 
 * This is a thin Node.js wrapper that delegates to the Python core.
 * For full functionality, use the Python CLI directly:
 *   python scripts/run_judge.py <mode> [options] -- <artifacts...>
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const SCRIPT_DIR = path.dirname(__dirname);
const PY_SCRIPT = path.join(SCRIPT_DIR, 'scripts', 'run_judge.py');

function runPy(argv) {
    return new Promise((resolve, reject) => {
        const child = spawn('python3', [PY_SCRIPT, ...argv], {
            stdio: 'inherit',
            cwd: SCRIPT_DIR
        });
        child.on('exit', code => process.exit(code));
        child.on('error', reject);
    });
}

// Simple passthrough — all logic lives in Python
const argv = process.argv.slice(2);

if (!fs.existsSync(PY_SCRIPT)) {
    console.error('Error: scripts/run_judge.py not found. Is llm-judge installed?');
    process.exit(1);
}

runPy(argv).catch(err => {
    console.error(err);
    process.exit(1);
});
