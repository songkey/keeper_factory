# Keeper Factory MVP v0.1 - Phase 2: Tech Stack & Project Skeleton

> Status: Confirmed design (Stage 3 output: development/deployment details, item 1)  
> Parent doc: `doc/MVP.0.1-base.md`  
> Sibling doc: `doc/MVP.0.1-phase2-model-layer.md` (item 2: model access layer)

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| S1 | Python & dependency management | **Python 3.12 + uv + pyproject.toml** |
| S2 | Object storage | **Aliyun OSS** (`oss2` SDK), client modeled after the proven `oss2ImageUpload` pattern |
| S3 | Data repository | **`data/` is an independent nested git repo** - F.4's per-loop memory commits must not pollute code history. Code repo gitignores `data/`; `config.json` points to it via `paths.data_root` |
| S4 | Model providers (v0) | **gpt + gpt-image-2**, vendored from the proven `llm_api.py` pattern; Gemini compatibility deferred (interfaces kept drop-in ready) |
| S5 | Per-node model configuration | Every model-calling node has its own `model_name` (and options) in `config.json`; defaults **gpt-5.5 / gpt-image-2** (see model-layer doc) |

## 2. Dependencies

| Purpose | Package | Rationale |
|---|---|---|
| Data models | **pydantic v2** | This is a schema-heavy system (experiment records, knowledge items, target cards, judge JSON, config); pydantic is the single source of truth for validation + serialization |
| Model APIs | **openai** SDK (+ httpx) | OpenAI-compatible endpoints; adaptations live inside the access layer |
| Templating | **jinja2** | P.1 slot templates and report rendering |
| YAML | **ruamel.yaml** | Preserves comments/ordering in knowledge files (git-diff friendly) |
| OSS | **oss2** | Aliyun OSS SDK (S2) |
| Email | stdlib `smtplib` + `imaplib` | No third-party dependency in v0; IMAP polling for approval replies |
| git ops | subprocess `git` | Simpler and more controllable than GitPython |
| CLI | **typer** | Commands as functions |
| Logging | **loguru** | Zero-config structured logging |
| Testing | **pytest** | - |

## 3. Project Skeleton

```
keeper_factory/
  pyproject.toml
  config.json                  # full config (consolidated in stage-3 item 5)
  doc/                         # design docs (this folder)
  prompts/                     # human-maintained prompt assets, hashed at load time
    p1_initial.jinja           # P.1 initial template (with slots)
    p3_eval_redline.jinja
    p3_eval_quality.jinja
    p4_synthesis.jinja
    p4_refine.jinja
  data/                        # runtime data root - INDEPENDENT nested git repo (S3)
    goldenset/                 #   13 cases + target_card.yaml
    memory/                    #   four knowledge types
    ledger/                    #   experiment records, signatures, P.1 chain, reports
  src/keeper_factory/
    config.py                  # pydantic config models + env var resolution
    schemas/                   # all data schemas (experiment/knowledge/target_card/judge_result)
    models/                    # model access layer (see model-layer doc)
      llm_api.py               #   vendored & trimmed LLMAPI/VLLMAPI/ImageEditAPI
      hub.py                   #   ModelHub: per-node model resolution + usage capture
    goldenset/                 # target card loading, rotation sampler
    memory/                    # knowledge CRUD, injection selector, promotion state machine
    judge/                     # Call-1/Call-2 orchestration, bidirectional pairwise protocol
    loop/                      # F.1-F.5 orchestration, checkpoints
    ledger/                    # record writing, signature calc, DNR index, budget
    report/                    # report & short-summary rendering
    mail/                      # SMTP send, IMAP poll, approval reply parser
    oss.py                     # upload client (with retry)
    cli.py                     # entrypoints
  tests/                       # named "tests" (plural)
    fixtures/                  # recorded responses for dry-run/replay mode
```

Organizing principle: **src modules map 1:1 to the C1-C5 components** (goldenset/memory/loop/judge/ledger), so design docs translate directly to code with no concept renaming.

## 4. CLI Command Set (initial)

| Command | Purpose |
|---|---|
| `kf init` | Initialize the `data/` nested git repo and directory scaffolding |
| `kf run --loops N` | Run N loops (respecting batch boundaries) |
| `kf run --dry-run` | Replay mode: recorded responses, no API spend (see model-layer doc) |
| `kf resume` | Resume from the last checkpoint |
| `kf status` | Current loop/batch/pending-review state |
| `kf approve` | Local approval entry (fallback when the email channel is unavailable) |

## 5. Open Items (deferred, tracked)

- Full `config.json` schema consolidation - stage-3 item 5
- Checkpoint file format - stage-3 item 4
- Deployment form (launchd/cron vs long-running process) - stage-3 item 6
