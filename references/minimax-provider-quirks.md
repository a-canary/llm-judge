# Minimax Provider — API Quirks and Fixes

## Verified working minimax API config

```
Base URL:  https://api.minimax.io/v1
Auth:      Bearer <key from pass show minimax/api-key>
Model:     MiniMax-M2.7
Endpoint:  /chat/completions (OpenAI-compatible)
```

**NOT** `/anthropic/v1` — that path returns 404.

## Pass store key path

```
pass show minimax/api-key        ← CORRECT (raw API key, starts with sk-cp-)
pass show api/minimax            ← WRONG (returns tree listing: "api/minimax\n└── api-key")
```

The `_provider_api_key()` in `run_judge.py` must use `minimax/api-key`.

## Thinking block format

MiniMax-M2.7 emits XML-style thinking blocks in its response:

```
<think>
analysis text here
</think>
```

These must be stripped before JSON parsing. Use:
```python
text = re.sub(r"<think>[^[]*?</think>", "", raw, flags=re.DOTALL)
```

The `<think>` tag does NOT have a language identifier prefix.

## Natural language rejection of JSON-only instructions

Even with "Respond ONLY with JSON" in the prompt, MiniMax-M2.7 sometimes returns
natural language instead of JSON when `max_tokens` is too low (e.g. 1024), causing
`JSONDecodeError: Expecting value`. Workarounds:

1. **Use `--provider cli --model claude-sonnet-4-6`** — reliable structured output
2. **Increase `max_tokens` to 4096** if staying on minimax API
3. Truncate artifact content to ≤50KB before evaluation to reduce prompt size

## HTTP 400 on large artifacts

Artifacts >~100KB cause `HTTPError: 400 Bad Request`. Truncate:
```bash
head -c 50000 large_artifact.md > truncated.md
```

## `hermes chat` CLI flags (for reference, prefer llm-judge)

```
hermes chat -Q                    # quiet mode (NOT --quiet)
hermes chat --ignore-user-config   # works
# --profile is NOT valid for hermes chat (use hermes profile use instead)
```
