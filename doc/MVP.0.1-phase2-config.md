# Keeper Factory MVP v0.1 - Phase 2: Full config.json Schema

> Status: Confirmed design (Stage 3 output: development/deployment details, item 5)  
> Parent doc: `doc/MVP.0.1-phase2-stack.md`  
> This document is the single consolidation point for all config fields scattered across the component designs. Source of each section is annotated.

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| CF1 | T0 location | **`prompts/t0.txt`** - alongside other human-maintained prompt assets, committed to the code repo, hashed into experiment signatures at load time |
| CF2 | Promotion thresholds | k=3 and worse-rate 25% (judge-spec "tunable initial values") are **promoted to config fields** (`promotion` section) |
| CF3 | Log location | **`data/ledger/logs/`** - inside the data repo (gitignored) so logs live next to run data for easy retrospectives |

## 2. Full Schema

```json
{
  "paths": {
    "data_root": "./data",                // independent nested git repo (S3)
    "data_remote": ""                     // remote for batch-boundary auto-push; empty = no push (DP1)
  },

  "loop": {                               // source: C3
    "batch_size": 5,                      // loops per batch (M1 approval boundary)
    "candidate_num": 3,                   // N, candidates per loop (L1)
    "context_window": 3,                  // recent summaries injected into F.1 (L5)
    "stagnation_threshold": 3             // m, stagnation flag threshold (L6)
  },

  "memory": {                             // source: C2
    "case_recipe_ttl": 5,                 // M2
    "max_injection_num": 3                // M5
  },

  "promotion": {                          // source: judge-spec section 6 (CF2)
    "min_samples": 3,                     // k: minimum secondary-validation samples
    "worse_rate_max": 0.25                // maximum worse rate
  },

  "models": {                             // source: model-layer (ML2)
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
  },

  "oss": {                                // source: C5 (LG2)
    "endpoint": "…",
    "bucket": "…",
    "prefix": "keeper_factory/mvp01",
    "access_key_env": "KF_OSS_AK",
    "secret_key_env": "KF_OSS_SK"
  },

  "mail": {                               // source: mail channel (MC1-MC4)
    "smtp_host": "…", "smtp_port": 465,
    "imap_host": "…", "imap_port": 993,
    "username": "…", "password_env": "KF_MAIL_PASSWORD",
    "from": "keeper-factory@…",
    "approvers": ["you@…"],
    "poll_interval_seconds": 300,
    "reminder_hours": 1
  },

  "logging": {
    "level": "INFO",
    "file": "ledger/logs/kf.log"          // relative to data_root; loguru rotating log, gitignored (CF3)
  }
}
```

## 3. Loading Rules (pydantic implementation)

- Every `*_env` field is resolved from environment variables at load time; a missing variable **fails startup immediately** (fail fast)
- Credentials are never written as values in `config.json` (the file is committed to git)
- The canonical hash of the whole loaded config is the `config_hash` used by the checkpoint (CK2); prompt files (including `prompts/t0.txt`, CF1) are hashed separately into `prompts_hash`
- Unknown fields are rejected (pydantic `extra="forbid"`) - catches typos like a misspelled node name

## 4. Environment Variables Summary

| Variable | Used by |
|---|---|
| `KF_LLM_API_KEY` | models.api |
| `KF_OSS_AK` / `KF_OSS_SK` | oss |
| `KF_MAIL_PASSWORD` | mail |

## 5. Open Items (deferred, tracked)

- A `config.example.json` template ships with the repo; real `config.json` may be gitignored if it ever carries non-secret but machine-specific values (decide at implementation)
