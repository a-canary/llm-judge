# Opus Judge — Criteria Template

Copy this file and pass it via `--criteria ./my_criteria.json` or `--criteria-text '...'` (JSON string).

## Rules

1. `dimensions` is an array of objects with fields: `name` (string), `weight` (float), `desc` (string)
2. All weights must sum to **exactly 1.0**
3. There is no limit on number of dimensions — use what's appropriate for the task

## Blank Template

```json
{
  "dimensions": [
    { "name": "DimensionName", "weight": 1.0, "desc": "What 'good' means here" }
  ]
}
```

## Example: General Writing

```json
{
  "dimensions": [
    { "name": "Correctness",    "weight": 0.30, "desc": "Facts are accurate, claims are supported" },
    { "name": "Completeness",   "weight": 0.25, "desc": "All parts of the topic are addressed" },
    { "name": "Clarity",        "weight": 0.20, "desc": "Writing is clear, unambiguous, well-structured" },
    { "name": "Conciseness",    "weight": 0.15, "desc": "No filler, appropriate length for the task" },
    { "name": "AudienceFit",    "weight": 0.10, "desc": "Appropriate for the intended reader" }
  ]
}
```

## Example: Code

```json
{
  "dimensions": [
    { "name": "Correctness",   "weight": 0.30, "desc": "Implements the spec correctly, no logic bugs" },
    { "name": "Idiomatic",     "weight": 0.20, "desc": "Uses language/framework conventions appropriately" },
    { "name": "Complexity",    "weight": 0.20, "desc": "No unnecessary complexity, appropriate abstractions" },
    { "name": "Readability",   "weight": 0.15, "desc": "Clear naming, good structure, low cognitive load" },
    { "name": "Robustness",    "weight": 0.15, "desc": "Handles errors, edge cases, and invalid input gracefully" }
  ]
}
```

## Example: Legal Arguments

```json
{
  "dimensions": [
    { "name": "LegalSoundness",   "weight": 0.35, "desc": "Arguments are legally valid and jurisdiction-appropriate" },
    { "name": "EvidenceQuality",  "weight": 0.25, "desc": "Claims are supported by cited evidence or precedent" },
    { "name": "Clarity",         "weight": 0.20, "desc": "Language is unambiguous, defined terms used correctly" },
    { "name": "Completeness",     "weight": 0.20, "desc": "All material terms and conditions are present" }
  ]
}
```

## Example: Medical Writing

```json
{
  "dimensions": [
    { "name": "Accuracy",      "weight": 0.40, "desc": "No factual errors; claims supported by cited evidence" },
    { "name": "Safety",       "weight": 0.25, "desc": "No guidance that could lead to harm if followed" },
    { "name": "Clarity",      "weight": 0.20, "desc": "Readable by the intended audience (clinician vs patient)" },
    { "name": "Completeness", "weight": 0.15, "desc": "Risk, contraindication, dosage are all addressed" }
  ]
}
```

## Example: Persuasive Essay

```json
{
  "dimensions": [
    { "name": "ArgumentQuality", "weight": 0.40, "desc": "Logical claims are sound and well-supported" },
    { "name": "Evidence",       "weight": 0.25, "desc": "Claims backed by credible evidence" },
    { "name": "Persuasiveness", "weight": 0.20, "desc": "Effectively convinces a skeptical reader" },
    { "name": "Clarity",        "weight": 0.10, "desc": "Clear, unambiguous prose" },
    { "name": "Brevity",        "weight": 0.05, "desc": "No filler; every paragraph earns its place" }
  ]
}
```
