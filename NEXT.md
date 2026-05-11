# NEXT.md — llm-judge

> Last updated: 2026-05-11

## Active

### N-0001 — Phase 2 kickoff: validate pipeliner module structure

| | |
|---|---|
| Category | feature |
| Score | 80 |
| Est | 0.5h |
| Source | sprint |
| Evidence | `pipeliner/llm_judge_module.ts` exists (193 lines) but `@pipeliner/sdk` not installed — cannot run `import { defineModule }`. `pipeliner/llm_judge_module.test.ts` also cannot execute. |
| Action | 1. `npm install @pipeliner/sdk` in project root (check package.json deps). 2. Run existing test suite with `node --test pipeliner/llm_judge_module.test.ts`. 3. Fix any TypeScript errors in the module. |
| Status | ✅ COMPLETE — committed db2d951 2026-05-11 |

## Completed (Phase 1)

| Item | Commit | Date |
|------|--------|------|
| Fix rank_swiss_elo return-key mismatch | 0f29c54 | 2026-05-11 |
| Fix compare_fn signature mismatch | 0f29c54 | 2026-05-11 |
| Fix test_judge.py CLI flag errors | 0f29c54 | 2026-05-11 |
| Add unit test suite (pytest) | 0f29c54 | 2026-05-11 |
| Add MiniMax thinking-block stripping | 0f29c54 | 2026-05-11 |
| Correct compare_fn content lookup | f697ffc | 2026-05-11 |
| Pipeliner module argparse fix + test suite | db2d951 | 2026-05-11 |

## Deferred

| Item | Blocked by |
|------|-----------|
| Pipeliner EA integration (USR-MSN-0001 trading) | N-0001 complete + SDK available |
| cc/ plugin publish manifest | Director approval |
| TypeScript rewrite of run_judge.py | CHOICES.draft.md approved |

## Out of Scope — needs Director review

### TypeScript rewrite of run_judge.py

Evidence: MEMORY notes prefer TS over Python; the canonical CLI is Python but the Node wrapper exists — full TS port would align with ecosystem preference.
Gap: CHOICES.draft.md designates Python as canonical. Rewrite requires Director approval and CHOICES.md update.
