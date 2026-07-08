# Keeper Factory

MVP v0.1 — self-evolving lab for image-editing judgment.

## Quick Start

```bash
uv sync --extra dev
cp config.example.json config.json
export KF_LLM_API_KEY=... KF_OSS_AK=... KF_OSS_SK=... KF_MAIL_PASSWORD=...
kf init --skip-secrets
```

## Dry-Run End-to-End (Step 7)

Run a full loop without calling external model APIs:

```bash
# 1) initialize data repository scaffold
kf init --skip-secrets

# 2) seed a minimal demo goldenset (1 case + anchor set)
kf seed-demo --skip-secrets

# 3) run one dry-run loop
kf run --dry-run --loops 1

# 4) inspect status
kf status
```

Artifacts to check after dry-run:

- `data/ledger/loops/loop_001.json`
- `data/ledger/reports/loop_001.md`
- `data/ledger/experiments/loop_001/`
- `data/ledger/checkpoint.json` (should be removed when loop completes)

## Real Warmup (Loop 0) Checklist

Before first real run:

1. Prepare 13-case goldenset (`5 bad / 5 good / 3 redline`) under `data/goldenset/`.
2. Ensure each case has `original.(jpg|png)` and `target_card.yaml`.
3. Prepare anchor set in `data/goldenset/anchors/anchor_v0.yaml`.
4. Verify environment variables:
   - `KF_LLM_API_KEY`
   - `KF_OSS_AK`
   - `KF_OSS_SK`
   - `KF_MAIL_PASSWORD`
5. Run warmup:

```bash
kf run --loops 1
```
