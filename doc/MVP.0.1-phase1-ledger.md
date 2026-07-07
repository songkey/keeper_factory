# Keeper Factory MVP v0.1 - Phase 1: Experiment Ledger (C5) Design

> Status: Confirmed design (Stage 2 output: component detailed design)  
> Component: C5 Experiment Ledger  
> Parent doc: `doc/MVP.0.1-base.md`  
> Positioning: **Memory stores distilled knowledge; the Ledger stores facts that happened.** Append-only, never mutated. It is the physical foundation of system-wide attribution and replay.

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| LG1 | Record granularity | **1 candidate execution+judgment = 1 experiment record**; each validation sample is its own record |
| LG2 | Artifact storage | **Images uploaded to OSS; URLs go into git.** OSS config lives in `config.json` |
| LG3 | Dedup | **Exact signature match only** in v0; semantic near-dup detection deferred |
| LG4 | `execution_failure` and do-not-repeat | **Exempt** - transient failures may be retried; only judged experiments enter DNR |
| LG5 | Budget | **Track-only, no hard circuit breaker** - the loop design already has a constant cost upper bound |
| LG6 | judge_result storage | **Full judge JSON uploaded to OSS, URL embedded**; a minimal inline summary (`verdict` + `failure_tags` + layer scores) stays in the record for high-frequency consumers (F.4, dedup index, reports) |

## 2. Directory Layout

```
ledger/
  experiments/
    loop_012/
      exp_loop012_main_c1.json      # one experiment = one JSON file
      exp_loop012_val_s2.json
  loops/
    loop_012.json                   # loop summary (F.5 short summary, stagnation check results)
  batches/
    batch_003.json                  # batch summary (review list + human reply outcomes)
  p1_versions/
    p1_v013.yaml                    # P.1 version chain (home of M6)
    CURRENT                         # pointer to the active version
  reports/
    loop_012.md                     # rendered Report + email dispatch status
  signatures.jsonl                  # dedup index (rebuildable from experiments/)
  budget.jsonl                      # per-loop cost bookkeeping
```

All of the above is git-managed metadata. **Binary artifacts (result images, edit prompts, full judge JSON) live on OSS**; records carry URLs plus sha256 checksums (tamper-evidence / verifiability).

## 3. Experiment Record Schema (the atomic unit)

```json
{
  "exp_id": "loop012_main_c1",
  "exp_sig": "sha256:…",
  "loop": 12,
  "batch": 3,
  "kind": "main",                     // main / validation / probe / warmup
  "case_id": "case_003",
  "strategy": {
    "p1_version": "p1_v012",
    "candidate_index": 1,
    "declared_dimension": "light_shadow",
    "strategy_digest": "sha256:…",     // normalized hash of the strategy description
    "injected_knowledge": ["pp_0003", "fn_0002"],
    "validates_recipe": null            // cr_id when kind = validation
  },
  "env": {
    "vlm": "qwen-vl@x.y",
    "edit_model": "…@v2.1",
    "judge_model": "…@z",
    "p1_hash": "…",
    "redline_prompt_hash": "…",
    "quality_prompt_hash": "…",
    "dimension_vocab": "dimension_vocab_v0",
    "anchor_set": "anchor_v1"
  },
  "artifacts": {
    "edit_prompt_url": "oss://…/loop_012/exp_…/edit_prompt.txt",
    "result_image_url": "oss://…/loop_012/exp_…/result.jpg",
    "result_image_sha256": "…"
  },
  "judge_summary": {                  // inline, for high-frequency consumers (LG6)
    "redline_pass": true,
    "verdict_vs_original": "better",
    "direction_score": 3,
    "execution_scores": {"realization": 3, "intensity": 2, "collateral_damage": 4},
    "failure_tags": ["over_saturation"]
  },
  "judge_result_url": "oss://…/loop_012/exp_…/judge_result.json",
  "status": "completed",              // completed / execution_failure / skipped_dnr
  "cost": {"vlm_calls": 5, "edit_calls": 1},
  "created_at": "2026-07-07T12:00:00+08:00"
}
```

Rationale for the inline summary (LG6 adaptation): F.4 synthesis, the dedup index, and report rendering all consume verdict conclusions at high frequency; pulling the full JSON from OSS each time is slow and adds a network dependency. The OSS full text is only needed for deep retrospectives.

## 4. Experiment Signature (`exp_sig`) and Dedup Rules

Signature = sha256 over the canonical JSON of:

```
case_id + declared_dimension + strategy_digest
+ injected_knowledge (sorted) + all env fields
```

Note: **`loop` and `candidate_index` are excluded** - the signature identifies "the semantically same experiment", independent of when it ran.

Do-not-repeat rules:

- v0 does **exact match only** (LG3): a new candidate whose signature already exists in `signatures.jsonl` is discarded and replaced (at most one replacement round, per C3)
- **`execution_failure` signatures do NOT enter DNR** (LG4) - failures may be transient; only judged experiments (regardless of verdict) enter
- `signatures.jsonl` line format: `{"sig": "…", "exp_id": "…", "verdict": "…", "loop": 12}`; if lost, fully rebuildable from `experiments/`

## 5. P.1 Version Chain

```yaml
# p1_versions/p1_v013.yaml
version: p1_v013
parent: p1_v012
created_loop: 12
slot_diffs:
  - slot: constraints
    before_hash: "…"
    after_hash: "…"
    diff_text: "…"
rationale: "This loop's evidence shows multi-instruction prompts cause full repaint; tightened to single instruction"
refine_exp_ref: loop012_refine       # the P.4_refine call that produced this diff
```

- The active version is referenced by the `p1_versions/CURRENT` pointer file
- Rollback = point `CURRENT` at any historical version; natively supported

## 6. Budget: Track-Only (LG5)

- `budget.jsonl`, one line per loop: call counts per type, deviation from the theoretical upper bound (~36 VLM / 6 edit)
- No hard circuit breaker in v0 - the loop already has a constant upper bound; adding enforcement now is over-engineering
- Cumulative cost is surfaced in every batch Report

## 7. config.json (OSS section)

```json
{
  "oss": {
    "endpoint": "…",
    "bucket": "…",
    "prefix": "keeper_factory/mvp01",
    "access_key_env": "KF_OSS_AK",
    "secret_key_env": "KF_OSS_SK"
  }
}
```

Security note: credentials are **referenced by environment variable name**, never written as values - `config.json` is committed to git, and plaintext keys in the repo would be a security incident.

## 8. Open Items (deferred, tracked)

- OSS provider/SDK choice and upload retry policy - Stage 3 (development/deployment) topic
- Whether `reports/` emails archive full sent content or just dispatch status + content hash (leaning full content; cheap and self-contained)
- Semantic near-duplicate detection for signatures (embedding similarity) - post-MVP
- Ledger compaction/archival policy when loop count grows large - post-MVP
