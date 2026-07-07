# Keeper Factory MVP v0.1 - Phase 1: Memory (C2) Design

> Status: Confirmed design (Stage 2 output: component detailed design)  
> Component: C2 Memory  
> Parent doc: `doc/MVP.0.1-base.md`  
> Positioning: Memory is a **knowledge store, not a log store**. Experiment process records belong to C5 Ledger; Memory holds only distilled judgment knowledge. The two cross-reference via experiment signatures.

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| M1 | Promotion approval | **Batch mode**: within a batch of n loops, auto-promote; at batch boundary, human approval by email (retroactive ratification). n=1 degenerates to per-loop approval |
| M2 | Case Recipe TTL | Configurable via `config.json` -> `memory.case_recipe_ttl`, **default 5** loops |
| M3 | `image_class` vocabulary | **Free text** for v0; accumulate first, derive vocabulary later |
| M4 | Pattern Patch conflicts | Presented to human with decision options: **merge** or **keep one** |
| M5 | Injection cap | `config.json` -> `memory.max_injection_num`, **default 3** |
| M6 | P.1 evolution history | **Not stored in Memory** - belongs to C5 Ledger |

## 2. Storage: Files + Git, No Database

At MVP scale (13 cases, single machine, low concurrency): **one knowledge item = one YAML file**, whole `memory/` directory managed by git.

```
memory/
  case_recipes/          # staging area (K.1)
    cr_0007.yaml
  pattern_patches/       # K.2
    pp_0003.yaml
  failure_notes/         # K.3
    fn_0005.yaml
  capability_notes/      # K.4
    cn_0002.yaml
```

Rationale:

- git diff natively provides the knowledge-evolution audit trail (who was promoted/demoted in which loop)
- zero-tooling human audit; rollback = git revert
- human edits are allowed but must go through git commit (traceability)
- database deferred until after Golden Set expansion

## 3. Common Envelope (all four knowledge types)

```yaml
id: pp_0003
type: pattern_patch            # case_recipe / pattern_patch / failure_note / capability_note
status: candidate              # candidate / pending_review / active / disputed / deprecated
created_loop: 12
updated_loop: 18
scope:                         # applicability boundary, used for retrieval matching
  dimensions: [light_shadow]   # closed vocabulary (dimension_vocab_v0)
  categories: [bad]            # bad / good / redline
  image_class: "backlit portrait"   # free text in v0 (M3)
confidence: medium             # low / medium / high (discrete tiers, no continuous values)
evidence: [exp_sig_a1, exp_sig_b2, exp_sig_c3]     # supporting experiment signatures
counter_evidence: []                                # contradicting experiment signatures
lineage:
  derived_from: cr_0007        # promotion source
```

Deliberate simplifications:

- **Confidence uses three discrete tiers**, no continuous scores or Bayesian updates. Rules: start `low`; each independent validation pass raises one tier; any counter-evidence lowers one tier AND flips status to `disputed`. Continuous confidence on a tiny sample set is false precision.
- **`disputed` state** (beyond the base doc's three states): knowledge with unresolved counter-evidence. Still injectable into P.1 but must carry a "disputed" marker; F.4 schedules re-validation or a human rules on it.

## 4. Status Machine and Batch Promotion (M1)

Loop batching: `config.json` -> `loop.batch_size = n`.

```
(F.4 meets promotion gate) ──► candidate    [auto within batch; effective immediately]
                                   │  batch ends
                                   ▼
                             pending_review [still injectable, marked "pending"]
                                   │  email approval
                    ┌──────────────┼──────────────────┐
                    ▼              ▼                   ▼
                 active        deprecated          disputed (re-validate)
```

- **Within batch (loops 1..n)**: knowledge meeting the promotion gate auto-promotes to `candidate`, immediately effective and injectable
- **At batch boundary (end of loop n)**: the loop pauses, sends the batch Report email, and waits
- Human replies with structured text to ratify: **approve / reject (-> deprecated) / dispute (-> re-validate)**
- The next batch starts only after approval completes
- `n = 1` degenerates to per-loop human approval
- Approval semantics are **retroactive ratification**: batch-internal auto-promotions take effect first; humans veto at batch end

## 5. Email Interaction Protocol (v0 human-machine interface)

- **Per loop end**: send loop Report (informational, non-blocking)
- **Per batch end**: send batch Report + pending-review list (blocks next batch). Reply with structured text lines, e.g.:

```
pp_0003: approve
pp_0005: reject
fn_0002: dispute
merge pp_0003 pp_0007
keep pp_0004 drop pp_0009
```

- **Pattern Patch conflicts (M4)** travel the same channel: the Report lists both sides plus two options (**merge** / **keep one**); human replies with the decision
- The future UI backend only replaces the carrier; protocol semantics stay identical. This verb set (approve / reject / dispute / merge / keep) is the future UI's operation set.

## 6. Type-Specific Payloads

### K.1 Case Recipe (staging area)

```yaml
case_id: case_003
declared_dimension: light_shadow
strategy_summary: "Declare protections first, then a single development instruction; edit prompt uses stepwise description"
p1_variant_ref: exp_sig_a1          # experiment that produced it
judge_result_ref: exp_sig_a1        # judge output lives in Ledger; only a reference here
validation_state: pending            # pending / validating / resolved
ttl_loops: 5                         # from config memory.case_recipe_ttl
```

Rule: a Case Recipe **must be resolved by F.4 within TTL** (promote or discard); expired items are auto-discarded. Prevents the staging area from becoming a junkyard.

### K.2 Pattern Patch

```yaml
principle: "Backlit portrait class: freeze identity and sky structure first, then develop subject lighting alone; avoid global re-exposure"
prompt_fragment: |                   # executable fragment injectable into P.1
  For backlit portraits: first declare frozen items (identity, sky structure),
  then issue a single light-development instruction for the subject only.
risk_note: "May trigger sky artifacts when sky occupies > 60% of the frame"
```

Design point: **dual-track principle + prompt_fragment**. The principle serves synthesis and human reading; the fragment serves direct F.1 consumption. Fragment-only storage degrades into a prompt collection, violating the overview doc's "Prompt is not the asset endpoint".

### K.3 Failure Note

```yaml
failure_pattern: "With 3+ parallel development instructions, the edit model tends to repaint the whole image"
trigger_conditions: "edit prompt contains multiple parallel enhancement verbs"
failure_tags: [full_repaint, identity_drift]     # aligned with the judge failure_tags vocabulary
avoid_rule: "Keep exactly one primary development instruction per edit prompt round"
```

### K.4 Capability Note

```yaml
model: image_edit_model@v2.1        # version pinning is mandatory
behavior: "Cannot brighten locally without shifting color temperature of adjacent regions"
reproductions: [exp_sig_x1, exp_sig_x2]
workaround: "Two steps: global exposure first, then local color-temperature pullback"
```

Rule: Capability Notes are **bound to a model version**; on model upgrade, all notes for that model automatically flip to `disputed` pending re-validation.

## 7. Read Path (how Memory is consumed)

F.1 context assembly policy:

1. **Failure Notes (active) are injected unconditionally** - bottom-line protection gets no retrieval filtering; v0 volumes are small enough
2. Pattern Patches / Capability Notes are matched against the current case by `scope` (dimension + category + fuzzy image_class), ordered by `status (active > candidate)` then `confidence (high > low)`, capped at **`memory.max_injection_num` (default 3)**
3. `disputed` knowledge carries a disputed marker when injected
4. The ids of all injected knowledge enter the experiment signature - this is what makes "was this knowledge actually useful" attributable

## 8. Write Path: Single Writer

- Only **F.4** may write Memory (promotion, demotion, discard)
- F.3 only produces Case Recipe drafts into the staging area
- Humans may edit at any time, but human edits also go through git commit (traceability)

## 9. config.json (Memory-related fields)

```json
{
  "loop": {
    "batch_size": 5
  },
  "memory": {
    "case_recipe_ttl": 5,
    "max_injection_num": 3
  }
}
```

## 10. Open Items (deferred, tracked)

- Email sending/receiving implementation (SMTP/IMAP polling vs mail-service webhook) - Stage 3 (development/deployment) topic
- Approval reply parsing robustness (typos, partial replies, timeout policy when no reply arrives) - Stage 3
- `image_class` vocabulary derivation trigger (suggested: review free-text accumulation at each batch boundary)
- Whether merged Pattern Patches keep both lineages (suggested: yes, `lineage.merged_from: [pp_a, pp_b]`)
