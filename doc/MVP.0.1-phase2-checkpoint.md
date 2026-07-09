# Keeper Factory MVP v0.1 - Phase 2: Checkpoint & Crash Recovery

> Status: Confirmed design (Stage 3 output: development/deployment details, item 4)  
> Parent doc: `doc/MVP.0.1-phase2-stack.md`

---

## 0. Premise

By design, most state is already persisted in real time (append-only Ledger, YAML Memory files, rebuildable signature index, P.1 `CURRENT` pointer, batch summary records). The checkpoint only needs to cover **in-flight loop state** - no heavyweight mechanism required.

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| CK1 | Checkpoint granularity | **Per F-step**, refined **per candidate/sample inside F.2 and F.4a** (the edit-call-burning steps) |
| CK2 | Config/prompt drift on resume | Checkpoint stores config + prompts hashes; mismatch on resume -> **refuse by default**, `kf resume --force` to override |
| CK3 | In-flight execution lost in a crash | **Re-execute** (accept one duplicate API cost in exchange for clean attribution: no record on disk = it never happened) |

## 2. Checkpoint File

Single file `ledger/checkpoint.json`, written via **temp file + atomic rename**:

> When the CLI runs with `--exp-name <exp_name>`, the checkpoint path becomes `ledger/exp/<exp_name>/checkpoint.json` (isolated per experiment namespace).

```json
{
  "loop": 12,
  "batch": 3,
  "stage": "f2",                       // f1 / f2 / f3 / f4a / f4b / f4c / f5 / batch_wait
  "inflight": {
    "main_case_id": "case_003",
    "candidates_total": 3,
    "candidates_done": ["loop012_main_c1"],   // those with experiment records written
    "validating_recipe": null
  },
  "config_hash": "…",
  "prompts_hash": "…",
  "updated_at": "…"
}
```

## 3. Write Points (CK1)

- After every F-step completes
- **Inside F.2 and F.4a**: after each candidate/sample finishes execution + record write - fine granularity here minimizes wasted edit-model spend on recovery
- All Ledger/Memory writes go through temp-file + rename (atomic); experiment record is written before the signature index update; recovery treats experiment records as the source of truth and rebuilds the index if needed

## 4. Resume Semantics (`kf resume`)

1. **Repair pass**: if the data repo is dirty (crash landed between a Memory write and its git commit) -> auto-commit with message `recovery: loop N`; then verify every experiment record referenced by the checkpoint exists
2. **Re-enter the current stage**: candidates/samples with existing experiment records are skipped; a candidate that was mid-execution without a record is **re-executed** (CK3 - in-flight API calls at crash time are considered lost)
3. **`batch_wait` stage**: check the "review email sent" flag in the batch record; if sent, resume polling only (reminder timer restarts); if not, send it now

## 5. Consistency Guards

- **Config/prompt drift interception (CK2)**: hash mismatch -> refuse with an explanatory message; `--force` overrides. Rationale: swapping e.g. a P.3 prompt mid-loop makes judgments within one loop non-comparable
- **Single-instance lock**: `ledger/.lock` containing the pid; prevents two processes writing concurrently; stale lock (dead pid) is reclaimed with a warning

## 6. Explicitly Out of Scope

- No resumption of half-finished LLM calls (in-flight calls are simply re-issued)
- No multi-machine / distributed recovery (single-machine MVP)

## 7. Open Items (deferred, tracked)

- Orphaned OSS artifacts from re-executed candidates (harmless; optional cleanup job post-MVP)
- Checkpoint schema versioning when loop structure evolves
