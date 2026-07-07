# Keeper Factory MVP v0.1 - Phase 1: Judge Spec

> Status: Confirmed design (Stage 2 output: component detailed design)  
> Component: C4 Judge Spec  
> Parent doc: `doc/MVP.0.1-base.md`  
> Judge Spec is human-defined and does NOT auto-evolve. Changes to this spec invalidate cross-loop score comparability and must be versioned.

---

## 0. Context: T0 and Its Implication for Judging

Current T0 (minimal version):

> Find the most promising dimension of this photo, and develop it into a final photographic work.

T0 is an **open-ended, divergent objective**: there is no single correct answer, and one photo may have multiple valid development directions. Two direct consequences:

1. The judge must evaluate **two separable things**, because their failure attribution differs completely:
   - **Direction**: did the system pick a dimension that is truly worth developing? (failure = value-discovery problem)
   - **Execution**: was the chosen dimension actually developed, sufficiently but not excessively? (failure = plan / edit prompt / model capability problem)
2. **Redlines are independent of both.** No matter how good the direction and execution are, identity drift, scene distortion, or artifacts are an immediate veto. This targets the most common failure mode of "developing potential": sacrificing authenticity for drama.

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Who defines the "promising dimensions"? | **(a)** Human pre-annotates 1-3 candidate dimensions in the Target Card; judge scores hit/quality against them |
| D2 | Single or split judge calls? | **Two calls**: redline check first, quality judgment only if redline passes |
| D3 | Dimension vocabulary | **Closed vocabulary + `other` escape hatch** |
| D4 | `same` verdict scoring | **same = 0**, not counted as positive gain |
| D5 | Does F.1 (candidate generation) see `candidate_dimensions`? | **No (kept secret)**. The system must discover dimensions itself; human annotations are the answer key for the judge only |
| D6 | Bidirectional pairwise comparison (2x cost) | **Accepted**. A-vs-B and B-vs-A both run; disagreement resolves to `same` |

## 2. Target Card Field Changes (imposed on C1)

New required fields per Golden Case:

```yaml
candidate_dimensions:            # 1-3 items, from closed vocabulary (Section 4)
  - dimension: light_shadow
    hint: "dusk side-light worth reinforcing"   # optional, judge-only
  - dimension: atmosphere
    hint: null
```

Visibility rules:

- `candidate_dimensions` and `hint` are visible to the **judge only** (Call-2)
- They are **never** injected into F.1 / F.2 context (per D5). Leaking them would turn the value-discovery test into answer-feeding.

## 3. Judge Structure: Four Layers

### Layer 0 - Redline Gate (hard fail, precedes all scoring)

Any single hit = `fail`; the candidate is excluded from pairwise ranking. Violations are still written into the Case Recipe (raw material for Failure Notes).

| Redline | Judging focus |
|---|---|
| Identity consistency | Face, body shape, hairstyle and other identity features must not drift |
| Factuality | No adding/removing/altering objects, text, or people in ways that change facts |
| Scene authenticity | Lighting logic, perspective, and materials must not violate physical intuition |
| Artifacts | Visible generation traces, structural collapse, edge blending failures |

Redline output is not just boolean: each violation records **type + location + evidence description**.

### Layer 1 - Direction Judgment

- The system (F.1/F.2 output) must **explicitly declare** the dimension it chose to develop. This is an interface requirement on upstream, not just an internal judge concern.
- Scoring:
  - If declared dimension hits one of the Target Card `candidate_dimensions`: score the fit (0-4)
  - If it misses: additionally judge "is the system's chosen dimension also plausible for this photo?" (a plausible miss is not necessarily 0)
- Output includes one-sentence rationale and, if applicable, the missed better dimension.

### Layer 2 - Execution Judgment

Each item scored 0-4 with mandatory evidence:

| Item | Question |
|---|---|
| Realization | Is there a perceptible change in the declared dimension, toward the intended direction? |
| Intensity | Is the change sufficient (under-development = wasted) yet not excessive (overdone = loses photographic feel, slides into "rendered look")? |
| Collateral damage | Were other already-established values of the original sacrificed to develop this dimension? |

### Layer 3 - Final Verdict (pairwise, not absolute scores)

**The verdict relies only on pairwise comparison + the redline gate. Layer 1/2 scores serve as attribution evidence, never as verdict inputs.** Rationale: absolute LLM scores drift across loops; pairwise comparisons are markedly more stable and human-consistent.

- `candidate vs original`: better / same / worse
- `candidate_A vs candidate_B` (within the same loop): ranking
- **Bidirectional protocol (D6)**: every pair is compared twice with positions swapped. If the two directions disagree, the result is `same`. This neutralizes LLM position bias at 2x Call-2 cost.

## 4. Closed Dimension Vocabulary (`dimension_vocab_v0`)

| Key | Name | Covers |
|---|---|---|
| `light_shadow` | Light and shadow | Contrast ratio, directional light, tonal layering |
| `color_mood` | Color mood | Tone, color relationships, saturation strategy |
| `subject_impact` | Subject impact | Subject prominence, clarity, texture |
| `composition` | Composition | Cropping, balance, visual guidance |
| `atmosphere` | Atmosphere / narrative | Weather feel, time-of-day feel, emotion |
| `moment` | Moment | Motion, expression, candid value |
| `other` | Escape hatch | Must attach textual explanation |

Governance:

- Vocabulary is versioned; the version id enters every experiment signature.
- If `other` exceeds **15%** of declarations within a loop cycle, trigger human vocabulary review.

## 5. Two-Call Judge Flow

```
Candidate ──► Call-1  Redline check  (P.3_eval_redline)
                 │ fail ──► out; record failure_tags; NO Call-2
                 │ pass
                 ▼
              Call-2  Direction + Execution + Verdict  (P.3_eval_quality)
```

- Call-1 failures skip Call-2 entirely (cost saving + clean separation of concerns).
- Both prompts are human-defined and fixed (no auto-evolution). Their hashes enter the experiment signature.

## 6. Scoring Rules for F.4 (secondary validation)

> Amended per Golden Set design: scoring is **category-aware**. A uniform `same = 0` would make good cases (where restraint IS success) permanently score-less and mislead sampling. See `doc/MVP.0.1-phase1-goldenset.md`.

Per validation experiment, by case category:

| Category | Success criterion | Scoring |
|---|---|---|
| bad | better | better = +1 / same = 0 / worse = -1 / redline fail = -2 |
| good | same or better (restraint) | same = +1 / better = +1 / worse = **-2** (regression penalized heavier) |
| redline | redline pass | pass = +1 / fail = **-3** (bottom line, heaviest penalty) |

Promotion condition (Case Recipe -> Pattern Patch), initial concrete values:

- Validated on **>= k = 3** distinct samples (different sub-types)
- **Total score > 0** AND **worse rate < 25%** AND **redline fail = 0**
- k and thresholds are tunable later; these are the explicit initial values.

## 7. Output JSON Schema

```json
{
  "case_id": "…",
  "candidate_id": "…",
  "judge_meta": {
    "judge_model": "model-name@version",
    "redline_prompt_hash": "…",
    "quality_prompt_hash": "…",
    "dimension_vocab": "dimension_vocab_v0"
  },
  "redline": {
    "pass": true,
    "violations": [
      {"type": "identity", "location": "face region", "evidence": "…"}
    ]
  },
  "direction": {
    "declared_dimension": "light_shadow",
    "hit_target_card": true,
    "score": 3,
    "rationale": "…",
    "missed_better_dimension": null
  },
  "execution": {
    "realization": {"score": 3, "evidence": "…"},
    "intensity": {"score": 2, "evidence": "overdone: sky saturation beyond natural range"},
    "collateral_damage": {"score": 4, "evidence": "…"}
  },
  "verdict_vs_original": "better",
  "pairwise": [
    {"against": "candidate_B", "result": "better", "bidirectional_agreed": true}
  ],
  "failure_tags": ["over_saturation"],
  "confidence": "high"
}
```

## 8. Judge Reliability Governance (from day one)

1. **Anchor set**: 5-10 human-labeled triples (original, candidate, expected verdict) embedded as few-shot anchors in the rubric, to suppress known LLM judge biases (preference for high saturation / high contrast).
2. **Version pinning**: judge model version + both P.3_eval prompt hashes are recorded in every experiment signature. A judge version change means historical scores are non-comparable.
3. **Human audit**: every loop, a fixed fraction of verdicts is human-reviewed; track the human-machine agreement rate. If it drops below threshold, recalibrate the rubric manually - do NOT auto-evolve P.3_eval.

## 9. Open Items (deferred, tracked)

- Concrete threshold for the human-machine agreement rate (suggest starting at 80%, adjust after data)
- Anchor set construction (blocked on Golden Set / Target Card work, next design doc)
- ~~Whether reference retouch images, when present, are given to Call-2 as improvement-direction hints~~ **Resolved: N/A for v0** - the Golden Set v0 contains no reference retouch images (text-only annotation). Revisit when reference images are introduced.
