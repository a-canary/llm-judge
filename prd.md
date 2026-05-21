# PRD — llm-judge cc-plugin-publish

## Problem Statement

llm-judge is functional locally (Python CLI + Node wrapper + pipeliner module) but
agents cannot install it through the cc plugin marketplace. Without a `cc/` plugin
manifest, every consumer must clone the repo, run `pip install -e .`, and wire up
credentials manually. This blocks USR-MSN-0001 (EA fitness selection in trading)
and USR-MSN-0002 (gate checks on generated documents) from being one-command
installable on fresh agent setups. The SKILL_reference.md is also drifting from
CLI flags after Phase 1 fixes — it must be synchronized as part of the publish.

## Solution

Add a `cc/` plugin manifest that wraps the existing CLI as an installable plugin
following the cc publish flow (`<plugin>@YYYY.MM.DD.HHMMSS` tag). Sync
SKILL_reference.md to current CLI behavior. Run the cc test+publish flow against
dev-cc/inbox so the green plugin lands in the marketplace. No code rewrite — this
is a packaging + docs sync slice only.

## User Stories

1. As a Director agent, I want to install llm-judge via `/plugin install llm-judge@cc`, so that I can use it on fresh agent sessions without cloning the repo.
2. As a Developer agent, I want SKILL_reference.md to match the current CLI 1:1, so that skill invocations do not fail on stale flag names (e.g. `--rank` vs `--elo-rank`).
3. As a Trading agent, I want llm-judge installable through cc, so that I can rank EA candidate strategies via the pipeliner module without manual setup.
4. As an OneNation operator, I want a gate-mode plugin installable on demand, so that I can validate generated documents against pass criteria without provisioning Python.
5. As a Director agent, I want the cc plugin to ship with the pipeliner module included, so that `defineModule` consumers get it via plugin install rather than separate clones.
6. As a Developer agent, I want a plugin version tag of form `llm-judge@YYYY.MM.DD.HHMMSS`, so that I can pin specific versions in cron jobs.
7. As a Developer agent, I want the cc publish pipeline to test the plugin before tagging, so that broken plugins never land in the marketplace.
8. As a Developer agent, I want SKILL_reference.md to document the keyring + pass + env var credential precedence with current commands, so that fresh installs do not silently fall back to no-key.
9. As a Director agent, I want a `plugin.json` (or equivalent cc manifest) at `cc/llm-judge/`, so that the marketplace discovery flow finds it on `publish.sh` runs.
10. As a Developer agent, I want the plugin install step to surface required environment variables (LLM_JUDGE_API_KEY, LLM_JUDGE_API_BASE), so that consumers know what to set before first call.
11. As a Trading agent, I want the pipeliner integration documented in the plugin README, so that I can wire EA fitness without spelunking through TypeScript source.

## Implementation Decisions

- Plugin manifest lives at `cc/llm-judge/` (per cc marketplace convention).
- Manifest references the existing `scripts/run_judge.py` and `pipeliner/llm_judge_module.ts` — no logic duplication.
- Version tag generated at publish time using UTC timestamp, e.g. `llm-judge@2026.05.14.140000`.
- SKILL_reference.md updated to reflect: (a) keyring-based credential lookup, (b) Phase 1 bug fixes (rank_swiss_elo key, compare_fn signature, MiniMax thinking-block strip), (c) `--elo-rank` / `--elo-class` post-positional argument requirement.
- Plugin manifest declares Python 3.9+ as runtime dependency; install hook reminds user to run `pip install -e .` or sets it up automatically per cc convention.
- pipeliner/llm_judge_module.ts included as exported module path; consumers import via plugin alias.
- No new code in scripts/ or references/ — packaging-only slice.

## Testing Decisions

- Run existing pytest suite (`pytest tests/ -q`) as plugin pre-publish gate.
- Run existing pipeliner test suite (`node --test pipeliner/llm_judge_module.test.ts`) as plugin pre-publish gate.
- Manual smoke test: install plugin into a fresh cc session, run `llm-judge review --prompt "test" test/fixtures/essay_a.md` — must exit 0.
- Manual smoke test: import `llm_judge_module` from plugin alias inside a pipeliner test — must instantiate without error.
- SKILL_reference.md flag-list audit: diff `--help` output against documented flags; must be 1:1.

## Out of Scope

- Phase 2 EA integration (lives in the trading project, not this repo).
- TypeScript rewrite of run_judge.py (deferred per NEXT.md; CHOICES.md still designates Python canonical).
- Auto-publishing on every commit (publish remains a manual cc test+publish flow run).
- Multi-model consensus or async LLM calls (out-of-scope at the CHOICES.md level).
- Adding new evaluation modes beyond review/gate/elo.
- Web UI or REST API surface.

## Further Notes

- This slice is the prerequisite for downstream agents to depend on llm-judge — until it ships through cc, every consumer is bespoke setup.
- After this slice merges + the cc publish lands green, Phase 2 EA integration unblocks in the trading project (it will install llm-judge from cc rather than vendoring).
- Re-running this slice after any future CLI flag change is required to keep SKILL_reference.md in sync — consider adding a CI lint that diffs `--help` against the doc.
