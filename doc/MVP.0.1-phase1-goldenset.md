# Keeper Factory MVP v0.1 - Phase 1: Golden Set & Target Card Spec

> Status: Confirmed design (Stage 2 output: component detailed design)  
> Component: C1 Golden Set (test set)  
> Parent doc: `doc/MVP.0.1-base.md`  
> Sibling doc: `doc/MVP.0.1-phase1-judge-spec.md` (this doc resolves its open item 3 and amends its Section 6)

---

## 1. Composition (v0)

| Item | Value |
|---|---|
| Total originals | 13 |
| bad case | 5 (verify lifting problem images toward target) |
| good case | 5 (verify restraint; anti-regression) |
| redline case | 3 (verify hard constraints hold) |
| Professional reference retouch images | **None in v0** - text-only annotation |

Consequences of "no reference images":

1. Judge Call-2 has no `Original -> Reference` improvement direction to compare against; direction/execution judgment relies entirely on `candidate_dimensions + hint`. Therefore **hint quality is upgraded from optional to critical input**.
2. The judge anchor set cannot come from reference retouches; it is built from a warm-up loop (Section 6).
3. Pattern Patch synthesis relies solely on judge verdicts + human hints. Accepted as an MVP simplification.

## 2. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| G1 | `hint` requirement | **Mandatory for bad cases**; optional for good/redline |
| G2 | Is `scene_brief` visible to F.1? | **No.** F.1/F.2 work fully autonomously from the image itself; all annotations serve the judge only |
| G3 | Scoring | **Category-aware** (see Section 5; amends judge-spec Section 6) |
| G4 | Sampling for v0 | **Deterministic rotation** replaces curriculum sampling ratios (see Section 7) |

## 3. Directory Layout

```
goldenset/
  case_001/
    original.jpg
    target_card.yaml
  case_002/
    …
```

## 4. Target Card Schema (`target_card.yaml`)

```yaml
case_id: case_001
category: bad                    # bad / good / redline
scene_brief: "Backlit portrait at dusk seaside; subject underexposed, sky blown out"

# ── Judge-only (D5: never enters F.1/F.2 context) ──
candidate_dimensions:            # 1-3 items, closed vocabulary (dimension_vocab_v0)
  - dimension: light_shadow
    hint: "Darken blown-out sky, lift subject, reinforce dusk side-light mood"  # mandatory for bad
must_keep:
  - "Subject identity features and pose"
  - "Natural transition between sea and sky"
forbidden:
  - "Adding objects absent from the original"
  - "Changing weather or time-of-day setting"

# ── Category-specific note (exactly one of the following) ──
problem_note: "Underexposed subject weakens impact; sky highlights clipped"      # bad
# established_note: "…"   # good: what makes this photo already established (basis for judging restraint)
# trap_note: "…"          # redline: which redline this case probes and what counts as crossing it
```

Visibility rules:

- **Everything in the Target Card is judge-only.** Per G2, even `scene_brief` is not given to F.1 (it exists for human disambiguation and judge context).
- F.1/F.2 receive only the original image (plus T0 / Memory / loop context as defined in the base doc).

## 5. Category-Specific Annotation Requirements & Scoring

### Annotation

| Category | Required fields | Notes |
|---|---|---|
| bad | `candidate_dimensions` (with mandatory `hint`), `must_keep`, `forbidden`, `problem_note` | hint states the expected development direction |
| good | `candidate_dimensions` (hint optional), `must_keep`, `forbidden`, `established_note` | `established_note` is the judge's basis for evaluating restraint ("should this photo be touched at all?") |
| redline | `must_keep`, `forbidden`, `trap_note` (hint optional) | The 3 cases should cover distinct traps: identity (clear face), factuality (text/logo), scene (complex lighting logic) |

### Category-aware scoring (amends judge-spec Section 6)

Uniform `same = 0` was designed for measuring lift on bad cases. For good cases, `same` IS success (restraint); for redline cases, `pass` IS success. Otherwise good cases could never contribute positive scores and the sampler would deem them worthless.

| Category | Success criterion | Scoring |
|---|---|---|
| bad | better | better = +1 / same = 0 / worse = -1 / redline fail = -2 |
| good | same or better | same = +1 / better = +1 / worse = **-2** (regression penalized heavier) |
| redline | redline pass | pass = +1 / fail = **-3** (bottom line, heaviest penalty) |

## 6. Warm-up Loop (loop 0) & Judge Anchor Set

Since no reference retouches exist, the judge anchor set is built via a warm-up round:

1. Run F.1/F.2 once over a few cases with the initial P.1 to produce candidates (no promotion, no memory writes)
2. Human labels each (original, candidate) pair with the expected verdict (+ violation notes where applicable)
3. Select 5-10 labeled triples as the few-shot anchor set embedded in P.3_eval rubrics
4. Anchor set is versioned; its version enters the experiment signature

Loop 0 outputs are excluded from all statistics and knowledge accumulation.

## 7. Small-Sample Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Validation exhaustion**: k=3 secondary validation over 5 bad cases inevitably reuses discovery samples for validation | Accept for MVP. All Pattern Patches are capped at `status: candidate` with scope noted as "valid on the 13-case set"; promotion to `active` requires an expanded set |
| **Curriculum sampling meaningless at n=13** | v0 downgrades to **deterministic rotation**: main experiment sample rotates bad -> bad -> good -> redline each loop; F.4 secondary validation draws same-category samples. Full curriculum sampler returns after set expansion |

## 8. Open Items (deferred, tracked)

- Concrete case selection for the 13 originals (human curation in progress: 5/5/3)
- Anchor set target size and refresh policy after judge model version changes
- Expansion plan trigger: define when the set grows beyond 13 (suggested: after MVP acceptance criteria pass)
