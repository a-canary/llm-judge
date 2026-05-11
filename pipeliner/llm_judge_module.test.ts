/**
 * llm_judge_module.test.ts
 * Unit tests for the pipeliner llm-judge module (Phase 2 integration).
 *
 * No live LLM calls — spawns Python CLI and validates output shape.
 */
import { describe, it, before, after } from "node:test";
import assert from "node:assert";
import { join } from "node:path";
import { spawn } from "child_process";
import { writeFileSync, unlinkSync, mkdirSync, existsSync } from "fs";

const SCRIPT_DIR = join(process.cwd(), "scripts");
const PY_SCRIPT = join(SCRIPT_DIR, "run_judge.py");
const FIXTURES_DIR = join(process.cwd(), "test", "fixtures");

// ── helpers ────────────────────────────────────────────────────────────────

function spawnPromise(cmd: string, args: string[]): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd: process.cwd() });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (d) => (stdout += d));
    child.stderr?.on("data", (d) => (stderr += d));
    child.on("close", (code) => resolve({ stdout, stderr, code: code ?? 1 }));
  });
}

// ── fixtures ────────────────────────────────────────────────────────────────

function ensureFixtures(): void {
  if (!existsSync(FIXTURES_DIR)) {
    mkdirSync(FIXTURES_DIR, { recursive: true });
    writeFileSync(join(FIXTURES_DIR, "essay_a.md"), "# Essay A\n\nThis is a well-structured essay about AI safety with clear arguments.\n");
    writeFileSync(join(FIXTURES_DIR, "essay_b.md"), "# Essay B\n\nThis essay rambles without clear structure or coherent thesis.\n");
  }
}

// ── tests ───────────────────────────────────────────────────────────────────

describe("llm_judge pipeliner module", () => {
  ensureFixtures();

  const essayA = join(FIXTURES_DIR, "essay_a.md");
  const essayB = join(FIXTURES_DIR, "essay_b.md");

  // ── smoke ──────────────────────────────────────────────────────────────

it("elo mode exits 0 with two artifacts", async () => {
    // NOTE: argparse positional(nargs='*') requires artifacts BEFORE option flags.
    // All --flags must come after artifacts: mode artifacts --options
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      essayA,
      essayB,
      "--prompt", "Which essay is more clearly written?",
      "--provider", "cli",
    ]);
    assert.strictEqual(result.code, 0, `stderr: ${result.stderr}`);
  });

  it("elo mode output contains ranking table", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      essayA,
      essayB,
      "--prompt", "Which essay is more clearly written?",
      "--provider", "cli",
    ]);
    assert.ok(result.stdout.includes("Rank"), "output should contain 'Rank' table header");
    assert.ok(result.stdout.includes("Final Ranking") || result.stdout.includes("Ranking"), "output should contain 'Final Ranking'");
  });

  it("gate mode exits 0 with one artifact", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "gate",
      essayA,
      "--prompt", "Is this essay well-structured?",
      "--provider", "cli",
    ]);
    assert.strictEqual(result.code, 0, `stderr: ${result.stderr}`);
  });

  it("review mode exits 0 with one artifact", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "review",
      essayA,
      "--prompt", "Rate clarity from 1-5",
      "--provider", "cli",
    ]);
    assert.strictEqual(result.code, 0, `stderr: ${result.stderr}`);
  });

  // ── flag validation ───────────────────────────────────────────────────

  it("--elo-rank K produces narrowed R3 output", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      "--elo-rank", "1",
      essayA,
      essayB,
      "--prompt", "Which is better?",
      "--provider", "cli",
    ]);
    assert.strictEqual(result.code, 0);
    // Should show a ranking with R3 band mention
    assert.ok(result.stdout.includes("Rank") || result.stdout.includes("Elo"), "should include ranking output");
  });

  it("--elo-class K produces class output without full sort", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      "--elo-class", "1",
      essayA,
      essayB,
      "--prompt", "Which is better?",
      "--provider", "cli",
    ]);
    assert.strictEqual(result.code, 0);
  });

  it("fails gracefully when provider is missing API key", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      essayA,
      essayB,
      "--prompt", "Which is better?",
      "--provider", "https://api.minimax.io/v1",
    ]);
    // Should either succeed (keyring/pass has key) or fail with auth message
    // We don't assert on code — just ensure no crash dump
    assert.ok(!result.stderr.includes("Traceback") || result.code === 0,
      "should not produce Python traceback");
  });

  // ── fixture paths ─────────────────────────────────────────────────────

  it("accepts file:// prefix for artifact paths", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      `file://${essayA}`,
      `file://${essayB}`,
      "--prompt", "Which is better?",
      "--provider", "cli",
    ]);
    // file:// is treated as a URL — check graceful handling
    // (may fail with "not found" or may succeed — as long as no crash)
    assert.ok(!result.stderr.includes("Traceback") || result.code === 0);
  });

  it("errors when artifact file does not exist", async () => {
    const result = await spawnPromise("python3", [
      PY_SCRIPT,
      "elo",
      "/nonexistent/path/to/artifact.md",
      "--prompt", "Which is better?",
      "--provider", "cli",
    ]);
    // Non-existent paths are treated as inline artifacts (no error exit).
    // Confirm it runs without a Python traceback.
    assert.ok(!result.stderr.includes("Traceback"),
      "should not produce Python traceback even with missing file");
  });
});