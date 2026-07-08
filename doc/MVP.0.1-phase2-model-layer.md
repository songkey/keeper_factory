# Keeper Factory MVP v0.1 - Phase 2: Model Access Layer

> Status: Confirmed design (Stage 3 output: development/deployment details, item 2)  
> Parent doc: `doc/MVP.0.1-phase2-stack.md`

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| ML1 | Structured output | Unified **`generate_json()`** wrapper: schema constraint injected from pydantic, validate on return, **one repair retry**, then `parse_failure` |
| ML2 | Per-node optional fields | `model_name` plus `max_long_edge` / `thinking` / `reasoning_effort` / `max_tokens`; judge nodes default **`max_long_edge: 1024` + thinking on** |
| ML3 | Retry layering | Access layer handles **transient errors only** (max 2 internal retries, exponential backoff); pipeline layer (F.2's single retry) handles **business failures only** |
| ML4 | Token accounting | **Categorized by `model_name` x `{input, input_cached, output}`** - billing rates differ per category; thinking tokens are billed as output and kept as an informational sub-field |
| ML5 | Dry-run mode | **Included in v0**: record/replay switch in the access layer; fixtures under `tests/fixtures/` |

## 2. Vendored `llm_api.py` (trimmed)

Source pattern: the proven `LLMAPI` / `VLLMAPI` / `ImageEditAPI` classes. Trim rules:

- **Keep**: class interfaces, per-call `model_name` override, transient-error detection (`is_transient_llm_error`), retry/backoff, token usage extraction, image resolution handling (`_image_edit_upload_dimensions` etc.)
- **Strip**: `keeper.gemini_official` import and all Gemini branches (v0 scope, per S4)
- **Preserve** the `api_mode` parameter and branch structure so re-adding Gemini later is drop-in

## 3. ModelHub: Per-Node Resolution

A process-level singleton reading `config.json` and exposing node-keyed calls:

```python
hub.generate_json(node="judge_redline", images=[...], user_prompt=..., schema=RedlineResult)
hub.image_edit(node="f2_image_edit", image=..., prompt=...)
```

Responsibilities:

1. Resolve `model_name` + options: `models.nodes[node]` -> fallback to `models.defaults`
2. Capture per-call token usage and attribute it to (node, model_name)
3. Record the resolved model into the experiment record's `env` section (already required by C5)
4. Route dry-run replay (ML5)

### Node registry (9 nodes)

| Node | API | Default model | Default options |
|---|---|---|---|
| `f1_candidate` | VLLM | gpt-5.5 | `max_long_edge: 768` |
| `f2_edit_prompt` | VLLM | gpt-5.5 | `max_long_edge: 768` |
| `f2_image_edit` | ImageEdit | gpt-image-2 | - |
| `judge_redline` | VLLM | gpt-5.5 | `max_long_edge: 1024`, thinking on |
| `judge_quality` | VLLM | gpt-5.5 | `max_long_edge: 1024`, thinking on |
| `judge_pairwise` | VLLM | gpt-5.5 | `max_long_edge: 1024`, thinking on |
| `f4_synthesis` | LLM | gpt-5.5 | thinking on |
| `f4_refine` | LLM | gpt-5.5 | thinking on |
| `f5_report` | LLM | gpt-5.5 | thinking **off** (plain text assembly, cost saving) |

Rationale for judge `max_long_edge: 1024`: the VLLM default of 512 is too low for artifact/identity judgment - systematic redline misses would follow.

**Caution**: changing `model_name` on the three judge nodes is a **major version event** (judge-spec version pinning): historical scores become non-comparable and the anchor set must be rebuilt. Cost-cutting with smaller models should start at low-risk nodes (`f5_report`, `f2_edit_prompt`).

### config.json (`models` section)

```json
{
  "models": {
    "api": {
      "request_url": "…",
      "api_key_env": "KF_LLM_API_KEY",
      "timeout_seconds": 180,
      "image_edit_timeout_seconds": 240
    },
    "defaults": { "vlm": "gpt-5.5", "edit": "gpt-image-2" },
    "nodes": {
      "f1_candidate":   { "model_name": "gpt-5.5", "max_long_edge": 768 },
      "f2_edit_prompt": { "model_name": "gpt-5.5", "max_long_edge": 768 },
      "f2_image_edit":  { "model_name": "gpt-image-2" },
      "judge_redline":  { "model_name": "gpt-5.5", "max_long_edge": 1024, "thinking": true },
      "judge_quality":  { "model_name": "gpt-5.5", "max_long_edge": 1024, "thinking": true },
      "judge_pairwise": { "model_name": "gpt-5.5", "max_long_edge": 1024, "thinking": true },
      "f4_synthesis":   { "model_name": "gpt-5.5", "thinking": true },
      "f4_refine":      { "model_name": "gpt-5.5", "thinking": true },
      "f5_report":      { "model_name": "gpt-5.5", "thinking": false }
    }
  }
}
```

## 4. `generate_json()` Protocol (ML1)

Used by all 6 JSON-output nodes (F.1 candidates, both judge calls, pairwise, F.4 x2):

1. Append an output-schema constraint (auto-generated from the pydantic model) to the prompt
2. Parse + validate the response against the model
3. On failure: **one repair retry** - send the raw output + validation errors back ("fix to valid JSON")
4. On second failure: record `parse_failure` (Ledger; treated like `execution_failure` - never judged/adopted)

## 5. Retry Layering (ML3)

| Layer | Handles | Policy |
|---|---|---|
| Access layer | Transient errors: network, 408/429/5xx (per `is_transient_llm_error`) | Max 2 internal retries, exponential backoff, transparent to callers |
| Pipeline layer (F.2 single retry) | Business failures: no image in edit result, JSON repair failed, empty output | Retry once, then `execution_failure` / `parse_failure` |

Attempt counts from both layers are recorded into the experiment record's `cost`.

## 6. Token Accounting (ML4)

Categories follow billing semantics: **`model_name` x `{input, input_cached, output}`**. Thinking tokens are billed within output; kept as an informational sub-field.

Experiment record `cost` section:

```json
"cost": {
  "calls": { "vlm": 5, "edit": 1 },
  "tokens": [
    { "model": "gpt-5.5",     "input": 12000, "input_cached": 8000, "output": 900, "output_thinking": 350 },
    { "model": "gpt-image-2", "input": 300,   "input_cached": 0,    "output": 0 }
  ]
}
```

`budget.jsonl` aggregates per loop by (node, model_name) - this directly supports the "swap in smaller models per node" decision: after a few batches the data shows which nodes burn the most tokens and what a swap would save.

## 7. Dry-Run / Replay Mode (ML5)

- `kf run --dry-run`: the access layer replays recorded responses; zero API spend
- Record-on-first-real-run, replay-thereafter; fixtures live in `tests/fixtures/`
- Primary value: **iterating on F.1-F.5 orchestration during development** without burning real calls; also powers deterministic pipeline tests

## 8. OSS Client

Modeled after the proven `oss2ImageUpload` pattern (`oss2` SDK):

- `upload_image` (path / PIL / numpy) / `upload_json` / `upload_file` / `get_public_url`
- Constructor params from `config.json` `oss` section; credentials resolved from env vars (`access_key_env` / `secret_key_env`)
- Add upload retry (3 attempts, backoff) - an OSS hiccup must not kill a loop; on final failure keep the local file and mark `upload_pending` for later re-sync

## 9. Open Items (deferred, tracked)

- Price table for cost-in-currency reporting (token counts are recorded now; multiply by rates later)
- Whether judge prompts also embed anchor images via URL vs re-upload per call (decide during implementation)
