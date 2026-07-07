# Keeper Factory MVP v0.1 - Base Design

> Status: Discussion draft (Stage 1 output: overall logic framework)  
> Scope: define components, collaboration relationships, and loop evolution only; no implementation details  
> Upstream docs: "Keeper Factory Overview v0.1", "Keeper Factory System Design v0.1", "Keeper Factory Lab v0.1"

---

## 1. Positioning and Boundaries

Keeper Factory MVP is an isolated lab, fully separated from Runtime. The core proposition to validate:

> Given human-defined target intent (T0), Golden Set, and forbidden boundaries,  
> can the system run self-loop experiments to generate candidate strategies, compare outcome gaps, iterate on failure points,  
> and accumulate cross-case reusable assets: Pattern Patch / Failure Note / Capability Note.

**Out of scope for this version:**

- No Runtime integration, no grayscale or Shadow comparison yet (next phase after MVP passes)
- No fully autonomous operation; humans define goals, judge spec, and periodic calibration
- Cost reduction is a constraint, not the target; result quality and knowledge production are the target

## 2. Processing Pipeline (Object being optimized)

```
Original image -> VLM (analyze + propose edit plan) -> edit prompt -> Image Edit Model -> edited result
```

- VLM system/user prompt quality is key judgment knowledge (J1)
- Image Edit Model prompt style knowledge is J1_edit, mainly accumulated as Capability Note

## 3. Global Objective T0

T0 is a human-written textual objective describing what a "valid/established" image result means. It is the single convergence north star.

- T0 is human maintained and not auto-evolved
- Judge, synthesis, and report must align with T0
- Any T0 change is a major version event and requires full regression

## 4. Component Overview

| Component | Responsibility | Evolution mode |
|---|---|---|
| C1 Test set (Golden Set) | Stable, repeatable, target-clear experimental ground | Human maintained, slowly expanded |
| C2 Memory | Store four knowledge types and lifecycle states | Auto-updated by loop, human-audited periodically |
| C3 Main loop | Execute hypothesis -> experiment -> evaluation -> validation -> accumulation | Core prompt P.1 evolves each loop |
| C4 Judge Spec | Define better/same/worse and hard redline gates | Human-defined, not auto-evolved |
| C5 Experiment Ledger | Signature, dedup, budget, report archive | System-recorded |

> **v0 human-machine interaction channel (added per Memory design)**: after each loop the Report is sent by email; batch-boundary approvals (knowledge promotion review, conflict resolution) are given by replying with structured text. A later UI backend will replace the carrier while keeping the same protocol semantics. See `doc/MVP.0.1-phase1-memory.md`.

### 4.1 C1 Test Set (Golden Set)

Each case includes at least: original image, Target Card (target intent, must-keep, forbidden items), optional professional reference retouch image.

Three mandatory sample categories:

- **bad case**: verify pushing problematic images toward target (measure upper-bound lift)
- **good case**: verify restraint and prevent breaking already-good images (anti-regression)
- **redline case**: verify hard constraints on identity, facts, scene authenticity, realism (bottom-line guard)

### 4.2 C2 Memory (Knowledge System)

| ID | Name | Nature | Function |
|---|---|---|---|
| K.1 | Case Recipe | **Temporary**, case-bound | Intermediate output, pending secondary validation |
| K.2 | Pattern Patch | Generalized guidance for a class of cases | Upper-bound guarantee; candidate production asset |
| K.3 | Failure Note | Generalized negative-pattern knowledge | Lower-bound protection |
| K.4 | Capability Note | Model capability/limitation knowledge for VLM/Edit Model | Accelerates K.2/K.3 iteration |

Common fields for every knowledge item:

- `scope`: applicability boundary (image type, scene, shooting style, etc.)
- `confidence`: confidence level (updated by repeated validation)
- `evidence`: supporting experiment signatures
- `status`: candidate / active / deprecated

Promotion gates (quantified, to prevent memory pollution):

| Path | Conditions |
|---|---|
| Case Recipe -> Pattern Patch | Significant positive gain on >= k different subtypes; no redline pass-rate drop; no good-case regression |
| Case Recipe -> Failure Note | Same negative optimization pattern repeatedly reproduced on multiple samples (>=2 independent reproductions) |
| Observation -> Capability Note | Model behavior reproducible in >=2 independent experiments |
| Any -> discard | Invalidated in later regression, or superseded by higher-confidence knowledge |

### 4.3 C3 Main Loop

Loop i (`c{i}`):

```
F.1.c{i} Sampling + generate N candidate plans
         Input: T0 | Memory | last n-loop context
         Output: N VLM prompt variants (constraint-limited edits)
        ->
F.2.c{i} Execute: VLM -> edit prompt -> Image Edit -> N results
        ->
F.3.c{i} Evaluate using Judge Spec against original/reference/candidates
         Output: structured Case Recipe (scores + evidence + failure tags)
        ->
F.4.c{i} Validate and synthesize:
         a) select valuable Case Recipes, run secondary validation on more samples
         b) promote qualified items to Pattern Patch / Failure Note / Capability Note and update Memory
         c) refine P.1 to steer next loop toward T0 convergence
        ->
F.5.c{i} Report: standardized summary of gains/losses
```

Sampling policy (curriculum sampling; replaces pure random):

- 40%: high-uncertainty or recently volatile cases (learning efficiency)
- 30%: historical failure clusters (repair lower bound)
- 20%: good-case regression guard (stability protection)
- 10%: random exploration (avoid local optimum)

F.5 report standard structure:

```
Hypothesis -> experiment matrix -> result distribution -> promoted/demoted/discarded knowledge -> next-loop plan
```

### 4.4 C4 Judge Spec

Must be fixed before F.3; defined by human; not auto-evolved:

- Fixed dimensions: target achievement, identity consistency, scene authenticity, artifacts, style coherence, etc.
- Hard-fail conditions per dimension (any hard fail = fail verdict before weighted scoring)
- Structured JSON output: scores + evidence + failure tags
- Reference usage: compare whether key improvement directions (Original -> Reference) are reflected in Candidate; no pixel-level matching

### 4.5 C5 Experiment Ledger

- Each experiment records `experiment_signature`: model version + prompt template hash + key params + case cluster
- Do-not-repeat: low-value historical signature hits are skipped or down-weighted
- Track budget and "saved-by-dedup" metrics in report

## 5. Prompt System

| ID | Location | Evolution mode |
|---|---|---|
| P.1.c{i} | F.1 candidate generation | **Core evolving prompt**, constraint-guided search |
| - | F.2 | no standalone prompt (edit prompt generated by VLM) |
| P.3_eval | F.3 evaluation / Case Recipe generation | human-defined, fixed |
| P.4_synthesis | F.4 cross-case synthesis/promotion decisions | semi-fixed, weakly evolvable with human review |

P.1 evolution rules (Prompt as Policy; constrained search):

- Parameterized template sections: objective / constraints / priorities / output schema
- At most 2-3 slots can change per loop
- Every change stores: diff + rationale + linked experiment signatures (traceable, rollback-ready, attributable)

Why split P.3_eval and P.4_synthesis:

- Evaluation must remain stable for cross-loop comparability
- Synthesis may evolve (with human checkpoint) for better generalization extraction

## 6. Exploration Governance: Stagnation Triggers

| Signal | Action |
|---|---|
| Main metric no lift for m consecutive loops | escalate from fine-tuning to strategy-level rewrite |
| bad-case improves while good-case regresses | enter protection mode; fix regressions first |
| redline failure exceeds threshold | freeze current candidate family; switch to capability boundary probing |
| many P.1 variants all ineffective | suspect non-prompt root cause; inspect plan/principles/model limits |

## 7. MVP Acceptance Criteria

1. **Repeatable loop**: same case experiments are reproducible, comparable, and reviewable
2. **Knowledge accumulation**: at least one secondary-validated Pattern Patch plus multiple Failure/Capability Notes
3. **Failure attribution**: failed runs produce explicit failure reasons, not just result images
4. **No regression**: good-case and redline stability maintained during evolution
5. **Prompt traceability**: every P.1 evolution has diff, rationale, and evidence chain

## 8. Post-MVP Direction (Out of scope here)

Expand Golden Set -> introduce Shadow comparison (Runtime/manual vs Factory on same inputs) -> only after sustained reliability move into Runtime Candidate.
