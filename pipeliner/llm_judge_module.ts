/**
 * llm_judge_module.ts
 * Pipeliner module for llm-judge — exposes review, gate, elo as a typed defineModule.
 *
 * Input: { mode, artifacts: string[], prompt, provider?, model?, criteria?, elo_rank?, elo_class? }
 * Output: { ranked?: string[], results: Record<string, any>, raw: string }
 *
 * Dispatches to scripts/run_judge.py via child_process spawn.
 * Canonical implementation is Python; this is the pipeliner integration layer.
 */
import { spawn } from "child_process";
import { existsSync } from "fs";
import { join, isAbsolute } from "path";
import { defineModule, objectSchema, schema } from "pi-pipeliner";
import type { CodeRunResult } from "pi-pipeliner";

// ── Types ────────────────────────────────────────────────────────────────────

export interface LlmJudgeInput {
  mode: "review" | "gate" | "elo";
  artifacts: string[];
  prompt: string;
  provider?: string;
  model?: string;
  criteria?: string;
  elo_rank?: number;
  elo_class?: number;
  rounds?: number;
}

export interface LlmJudgeOutput {
  ranked?: string[];
  results: Record<string, any>;
  raw: string;
  mode: string;
  exitCode: number;
}

// ── Schema helpers ────────────────────────────────────────────────────────────

const artifactSchema = schema((v: unknown): string => {
  if (typeof v !== "string") throw new Error("artifact must be a string");
  if (!v.trim()) throw new Error("artifact cannot be empty");
  return v;
});

// ── Module definition ────────────────────────────────────────────────────────

export const llmJudge = defineModule({
  name: "llm-judge",
  description: "Swiss Elo ranking, pass/gate, and qualitative review via LLM",
  input: objectSchema<LlmJudgeInput>({
    mode: "string",
    artifacts: "array",
    prompt: "string",
    provider: "string",
    model: "string",
    criteria: "string",
    elo_rank: "number",
    elo_class: "number",
    rounds: "number",
  }),
  output: objectSchema<LlmJudgeOutput>({
    ranked: "array",
    results: "object",
    raw: "string",
    mode: "string",
    exitCode: "number",
  }),
  rules: (_input, output) => [
    () => typeof output.raw === "string" || "output.raw must be a string",
    () => typeof output.exitCode === "number" || "output.exitCode must be a number",
    () => output.exitCode === 0 || `llm-judge exited with code ${output.exitCode}`,
  ],
  async run(_ctx, input): Promise<CodeRunResult<LlmJudgeOutput>> {
    // ── Locate Python script ──────────────────────────────────────────────
    const scriptDir = process.cwd();
    const pyScript = join(scriptDir, "scripts", "run_judge.py");

    if (!existsSync(pyScript)) {
      throw new Error(
        `llm-judge: scripts/run_judge.py not found at ${pyScript} — ` +
        "is llm-judge installed in this working directory?"
      );
    }

    // ── Build argument list ───────────────────────────────────────────────
    // argparse positional(nargs='*') breaks when 3+ optional flags precede
    // any positional.  FIX: put ALL artifacts first (before any --flags),
    // then use `--` separator before options so argparse treats everything
    // after `--` as positional.
    const argv: string[] = [input.mode];

    // Resolve artifact paths (must be absolute or relative to cwd)
    for (const art of input.artifacts) {
      const abs = isAbsolute(art) ? art : join(scriptDir, art);
      argv.push(abs);
    }

    // `--` tells argparse: everything after is positional/artifacts
    argv.push("--");

    if (input.provider) {
      argv.push("--provider", input.provider);
    }
    if (input.model) {
      argv.push("--model", input.model);
    }
    if (input.criteria) {
      argv.push("--criteria", input.criteria);
    }
    if (input.rounds != null) {
      argv.push("--rounds", String(input.rounds));
    }

    // Elo-specific narrowing
    if (input.mode === "elo") {
      if (input.elo_rank != null) {
        argv.push("--elo-rank", String(input.elo_rank));
      }
      if (input.elo_class != null) {
        argv.push("--elo-class", String(input.elo_class));
      }
    }

    argv.push("--prompt", input.prompt);

    // ── Spawn Python process ──────────────────────────────────────────────
    const child = spawn("python3", [pyScript, ...argv], {
      cwd: scriptDir,
      env: { ...process.env },
    });

    let stdout = "";
    let stderr = "";

    child.stdout?.on("data", (d) => (stdout += d));
    child.stderr?.on("data", (d) => (stderr += d));

    const exitCode = await new Promise<number>((resolve) => {
      child.on("close", (code) => resolve(code ?? 1));
      child.on("error", (err) => {
        stderr += String(err);
        resolve(1);
      });
    });

    const raw = stdout || stderr;

    // ── Parse ranking from raw output (elo mode) ─────────────────────────
    let ranked: string[] | undefined;
    if (input.mode === "elo") {
      ranked = parseRankingFromOutput(raw);
    }

    const results: Record<string, any> = {};
    if (input.mode === "review" || input.mode === "gate") {
      results["output"] = raw;
    }

    return {
      result: {
        ranked,
        results,
        raw,
        mode: input.mode,
        exitCode,
      },
    };
  },
});

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * Parse artifact IDs from Swiss Elo markdown output.
 * Handles both full ranking (sorted top-K) and class (pivot survivor) modes.
 *
 * Looks for table rows like:
 *   | 1    | artifact_id   | 1532.1 | 3       |
 * or
 *   | ★    | artifact_id   | 1521.4 | 3       |
 */
function parseRankingFromOutput(raw: string): string[] {
  const ranked: string[] = [];
  const lines = raw.split("\n");

  for (const line of lines) {
    // Skip separator lines
    if (line.match(/^\s*\|[-:]+\|/)) continue;
    // Match table row: optional rank number/star, artifact id (alphanumeric + dash/underscore), Elo, matches
    const match = line.match(/^\s*\|\s*(?:\d+|[*])\s*\|\s*([a-zA-Z0-9_-]+)\s*\|/);
    if (match) {
      ranked.push(match[1]);
    }
  }

  return ranked;
}