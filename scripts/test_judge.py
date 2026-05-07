#!/usr/bin/env python3
"""
Test harness for llm-judge Swiss Elo.
Run: python3 scripts/test_judge.py

Uses 4 sleep-essay artifacts (a-d_sleep_*.md) as fixtures.
Artificts are written to /tmp/llm_judge_test/ on each run.
Timeouts are sized for ~45s/claude-call.
"""

import os
import sys
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
SCRIPT = SKILL_DIR / "scripts" / "run_judge.py"
ARTIFACT_DIR = Path("/tmp/llm_judge_test")
ARTIFACT_DIR.mkdir(exist_ok=True)

ARTIFACTS = {
    "a_sleep_important.md": (
        "# Why Sleep is Important\n\n"
        "Sleep is essential for human health. During sleep, the brain consolidates memories "
        "and removes toxins. Lack of sleep leads to impaired cognition, weakened immunity, "
        "and increased accident risk. Adults should aim for 7-9 hours per night. "
        "Chronic sleep deprivation is linked to obesity, diabetes, and cardiovascular disease.\n\n"
        "In conclusion, prioritizing sleep improves both mental and physical well-being."
    ),
    "b_sleep_matters.md": (
        "# Why Sleep Matters\n\n"
        "Sleep is critical for survival. The body uses sleep to repair tissues, regulate hormones, "
        "and process emotions. Studies show that people who sleep less than 6 hours per night "
        "have higher mortality rates. Even one night of poor sleep can reduce alertness and "
        "decision-making abilities.\n\n"
        "Therefore, sleep should be treated as a non-negotiable pillar of health "
        "alongside nutrition and exercise."
    ),
    "c_sleep_quality.md": (
        "# The Importance of Sleep\n\n"
        "Humans spend one-third of their lives sleeping. While sleeping, the brain cycles through "
        "REM and non-REM stages that serve different restorative functions. REM sleep supports "
        "emotional regulation while deep non-REM sleep promotes physical recovery.\n\n"
        "Getting enough quality sleep enhances creativity, problem-solving, and emotional resilience."
    ),
    "d_sleep_epidemic.md": (
        "# Sleep and Health\n\n"
        "Insufficient sleep is a public health epidemic. According to the CDC, 1 in 3 adults "
        "don't get enough sleep. Sleep deprivation impairs judgment similar to alcohol intoxication. "
        "It also suppresses leptin (the fullness hormone) and increases ghrelin (hungner hormone), "
        "leading to weight gain.\n\n"
        "Bottom line: sleep is not a luxury -- it is a biological necessity."
    ),
}

for name, text in ARTIFACTS.items():
    (ARTIFACT_DIR / name).write_text(text)

ARTIFACT_PATHS = [str(ARTIFACT_DIR / n) for n in sorted(ARTIFACTS.keys())]
PROMPT = "Which essay is most informative and well-structured?"


def run(mode, extra_args=None, timeout=300, desc="", n_artifacts=None):
    paths = ARTIFACT_PATHS[:n_artifacts] if n_artifacts else ARTIFACT_PATHS
    args = [sys.executable, str(SCRIPT), mode] + paths + ["--prompt", PROMPT]
    if extra_args:
        args.extend(extra_args)
    print(f"\n{'='*60}\n{desc}\n{'='*60}")
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    print(r.stdout[:3000])
    if r.returncode != 0:
        print("STDERR:", r.stderr[:500])
    return r.returncode == 0


if __name__ == "__main__":
    results = []
    results.append(("review",   run("review", timeout=360, desc="TEST: review (4 artifacts)")))
    results.append(("gate",     run("gate",   timeout=180, desc="TEST: gate (2 artifacts)", n_artifacts=2)))
    results.append(("elo-full",  run("elo",    timeout=480, desc="TEST: elo full (4 artifacts, 3 rounds)")))
    results.append(("elo-topk",  run("elo",    extra_args=["--rank","2"],   timeout=480, desc="TEST: elo top-2")))
    results.append(("elo-band",  run("elo",    extra_args=["--rank","2..3"], timeout=480, desc="TEST: elo band 2-3")))

    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    for name, ok in results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
