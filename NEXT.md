# NEXT.md — llm-judge
# DRAFT — pending Director/user approval

## Fix rank_swiss_elo return-key mismatch

Generated: 2026-05-09 | Category: bug | Score: 90 | Est: 0.5h
Scope: In scope
Source: director
Evidence: elo.py returns dict key "ranked" (list of str) but mode_elo reads "ranked_ids" — elo mode crashes at runtime on the ranked_ids lookup.
Action: Align key name — rename "ranked" → "ranked_ids" in elo.py return dict, verify mode_elo and test_judge.py both pass.
Status: ✅ COMPLETE — committed 0f29c54 2026-05-11

## Fix compare_fn signature mismatch between elo.py and run_judge.py

Generated: 2026-05-09 | Category: bug | Score: 88 | Est: 0.5h
Scope: In scope
Source: director
Evidence: elo.py calls compare_fn(task, dims_hash, a, b, cache) but run_judge.py's compare_fn closure expects (a_id, a_elo, a_content, b_id, b_elo, b_content) — elo mode will TypeError on every comparison.
Action: Align signatures — update elo.py to call compare_fn(a, b) with ArtifactElo objects; let run_judge.py closure receive those and extract what it needs.
Status: ✅ COMPLETE — committed 0f29c54 2026-05-11

## Fix test_judge.py CLI flag errors (--rank / --rank 2..3)

Generated: 2026-05-09 | Category: bug | Score: 75 | Est: 0.5h
Scope: In scope
Source: director
Evidence: test_judge.py calls CLI with --rank and --rank 2..3 but CLI defines --elo-rank and --elo-class — integration test is broken out of the box.
Action: Update test_judge.py test cases to use --elo-rank 2 and --elo-class 2 respectively; remove range syntax (unsupported).
Status: ✅ COMPLETE — committed 0f29c54 2026-05-11

## Add unit test suite (pytest, no live LLM calls)

Generated: 2026-05-09 | Category: feature | Score: 72 | Est: 3h
Scope: In scope
Source: director
Evidence: No unit tests exist — only a slow integration harness that requires live claude CLI. Bugs above could have been caught at commit time.
Action: Create tests/ directory with pytest; cover FIFOCache symmetry/eviction, rank_swiss_elo pairing invariants, parse_pairwise_result JSON+regex fallback, validate_criteria weight sum, load_artifact paths.
Status: ✅ COMPLETE — committed 0f29c54 2026-05-11

## Add MiniMax thinking-block stripping to parse_pairwise_result

Generated: 2026-05-09 | Category: bug | Score: 65 | Est: 0.5h
Scope: In scope
Source: director
Evidence: SKILL_reference.md documents that MiniMax emits " op " thinking blocks that corrupt JSON parsing, but parse_pairwise_result does not strip them — every MiniMax pairwise call fails to parse.
Action: Add regex strip for `<thinking>...</thinking>` (or ` op ` pattern) before JSON parse in parse_pairwise_result.
Status: ✅ COMPLETE — committed 0f29c54 2026-05-11

## Deferred

### Pipeliner module (Phase 2)

Generated: 2026-05-09
Source: director
Reason: Blocked on Phase 1 bugs being fixed first; pipeliner integration has no value if the core CLI is broken.
Unblock: Phase 1 bug fixes complete + pytest suite green.

## Out of Scope — needs Director review

### TypeScript rewrite of run_judge.py

Evidence: MEMORY notes prefer TS over Python; the canonical CLI is Python but the Node wrapper exists — full TS port would align with ecosystem preference.
Gap: CHOICES.draft.md designates Python as canonical. Rewrite requires Director approval and CHOICES.md update.
