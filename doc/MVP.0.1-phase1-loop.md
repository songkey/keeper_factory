# Keeper Factory MVP v0.1 - Phase 1: Main Loop (C3) Design

> Status: Confirmed design (Stage 2 output: component detailed design)  
> Component: C3 Main Loop  
> Parent doc: `doc/MVP.0.1-base.md`  
> Dependencies (all finalized): C1 Golden Set (`MVP.0.1-phase1-goldenset.md`), C2 Memory (`MVP.0.1-phase1-memory.md`), C4 Judge Spec (`MVP.0.1-phase1-judge-spec.md`)

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| L1 | Candidates per main experiment (N) | `config.json` -> `loop.candidate_num`, **default 3** |
| L2 | Validation budget | **At most 1 validation campaign per loop**; staging queue relies on TTL for natural eviction |
| L3 | P.1 refinement prompt | **New `P.4_refine`**: a standalone, human-defined, fixed meta-prompt, separate from `P.4_synthesis` |
| L4 | Same-source recipes | Only the pairwise **top-1** candidate's recipe enters the staging area |
| L5 | Prior-loop context | Structured short summaries of recent loops, `config.json` -> `loop.context_window`, **default 3** |
| L6 | Stagnation threshold (m) | `config.json` -> `loop.stagnation_threshold`, **default 3** |
| L7 | Inter-candidate pairwise | **Kept** in v0 (re-evaluate after several batches of data) |

## 2. Loop Shape: One Loop = One Main Experiment + At Most One Validation Campaign

Validating every valuable recipe immediately would make per-loop cost explode. Instead:

- **Main experiment**: deterministic rotation picks 1 main sample; generate and judge N candidates
- **Validation campaign**: validate **at most 1** Case Recipe per loop (highest-value pending item in the staging area), across k=3 same-category samples
- Recipes that never win the queue expire via TTL (5 loops) - this is the TTL mechanism's true purpose: validation bandwidth is scarce, and the queue self-cleans

Result: per-loop cost has a **constant upper bound**; budget is predictable.

## 3. The Five Steps in Detail

### F.1 Sampling + Candidate Generation

1. **Main sample selection**: category rotates `bad -> bad -> good -> redline` (G4); within a category, pick the least-recently-used case
2. **Context assembly**: `T0` + Memory injection (per C2 read-path rules) + **structured short summaries of the last `loop.context_window` loops** (not full Reports) + current P.1 version
3. **Single call generates N candidates**: one P.1 call produces N differentiated strategies (not N independent calls). Diversity is demanded explicitly in the prompt ("the N strategies must differ in explored dimension or control structure"), which also simplifies dedup
4. Each candidate gets an experiment signature; a do-not-repeat hit discards the candidate and requests a replacement (**at most one replacement round**)

Every candidate must explicitly declare: `declared_dimension` (closed vocabulary) + strategy description + edit-plan skeleton for the edit model.

### F.2 Execution

- Per candidate: VLM generates edit prompt -> edit model produces the image
- Failure handling: **one retry**; a second failure is recorded as `execution_failure` (into Ledger, never judged), no replacement
- All intermediate artifacts (edit prompt, result image, model params) are archived to disk; paths recorded in the experiment signature

### F.3 Judging

- Per Judge Spec: Call-1 redline -> Call-2 quality + pairwise (vs original bidirectional, inter-candidate bidirectional; L7 keeps inter-candidate)
- Each surviving candidate yields a Case Recipe draft with `validation_state: pending`
- **Only the pairwise top-1 recipe of the N same-source candidates enters the staging area** (L4); the rest are recorded in Ledger only - prevents the staging area from flooding with same-origin strategies

### F.4 Validation + Synthesis + P.1 Refinement (three sub-steps)

- **F.4a Validation campaign**: take the highest-value pending recipe from staging (ranking: main-experiment verdict `better`, high Layer-2 scores, wide scope coverage); run F.2+F.3 on k=3 same-category samples; apply the category-aware scoring table
- **F.4b Synthesis**: `P.4_synthesis` decides promote / discard / convert to Failure Note or Capability Note; writes Memory (the single-writer rule executes here)
- **F.4c P.1 refinement**: the standalone fixed meta-prompt **`P.4_refine`** takes all of this loop's evidence and outputs a **slot-diff proposal for P.1** (max 3 slots). New version tagged `p1_v{i+1}`, effective next loop. The P.1 version chain lives in Ledger (M6)

Rationale for splitting `P.4_synthesis` and `P.4_refine` (same as the P.3 split): knowledge synthesis and exploration-strategy adjustment are different responsibilities; merging them into one call pollutes attribution.

### F.5 Report

Standard structure (already fixed): hypothesis -> experiment matrix -> result distribution -> promoted/demoted/discarded knowledge -> next-loop plan. Plus:

- **Structured short summary** (~10 lines) for future loops' F.1 context (this is exactly what L5 consumes)
- **Stagnation checks**:
  - main metric flat for `loop.stagnation_threshold` consecutive loops -> Report flags "strategy-level rewrite recommended" (red), surfaced to human at batch end
  - bad-case lift with good-case regression -> next loop forcibly becomes a good-case protection round
- Email dispatch (per-loop informational; batch-end blocking for review)

## 4. Per-Loop Cost Budget (upper bound at N=3, k=3)

| Step | VLM calls | Edit model calls |
|---|---|---|
| F.1 candidate generation | 1 | 0 |
| F.2 main experiment | 3 (edit prompts) | 3 |
| F.3 main-experiment judging | 3 redline + 3 quality + ~9 bidirectional pairwise | 0 |
| F.4a validation campaign | 3 + 3 redline + 3 quality + 6 pairwise | 3 |
| F.4b/c synthesis + refine | 2 | 0 |
| **Total upper bound** | **~36** | **6** |

Comfortably runnable on a single machine. If cost must be cut, the first target is inter-candidate pairwise (~9 calls), replaceable by Layer-2 score ranking - deferred per L7 until real batch data exists.

## 5. config.json (loop fields, consolidated)

```json
{
  "loop": {
    "batch_size": 5,
    "candidate_num": 3,
    "context_window": 3,
    "stagnation_threshold": 3
  }
}
```

| Field | Meaning | Default |
|---|---|---|
| `batch_size` | loops per batch (M1, promotion approval boundary) | 5 |
| `candidate_num` | N, candidates per main experiment | 3 |
| `context_window` | number of recent loop summaries injected into F.1 | 3 |
| `stagnation_threshold` | m, consecutive no-lift loops before flagging strategy rewrite | 3 |

## 6. Open Items (deferred, tracked)

- Loop state checkpointing / crash resumability (per-F-step checkpoint files) - Stage 3 topic
- Exact recipe-value ranking formula for F.4a (initial: verdict > Layer-2 total > scope breadth; tune with data)
- Whether the good-case protection round (stagnation trigger 2) also suspends the validation campaign that loop (leaning yes, to keep cost bounded)
