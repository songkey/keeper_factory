# Keeper Factory MVP v0.1 - Phase 2: Running Form & Deployment

> Status: Confirmed design (Stage 3 output: development/deployment details, item 6 - final)  
> Parent doc: `doc/MVP.0.1-phase2-stack.md`

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| DP1 | Data repo remote backup | **Yes** - remote address configured in `config.json` (`paths.data_remote`); auto `git push` at every batch boundary; **empty value = no push** |
| DP2 | Crash notification email | **Yes** - best-effort `[KF][CRASH]` email before exit on unhandled exceptions |

## 2. Running Form: Foreground CLI, No Daemon

`kf run --loops 15` runs as a foreground process (inside tmux / nohup):

- Batch boundaries block on email approval anyway; a resident service adds nothing
- A run covers a finite loop count and exits naturally; crashes are handled by `kf resume` (checkpoint doc)
- No launchd/systemd service in v0 - that belongs to the future UI-backend era

Typical flow: `kf run --loops 15` -> pauses every 5 loops and sends the review email -> reply `all ok` from the phone -> process resumes automatically -> exits when done. Check progress anytime with `kf status` (reads checkpoint + budget, non-intrusive).

## 3. Crash Notification (DP2)

On any unhandled exception, before exiting the process best-effort sends:

```
Subject: [KF][CRASH] loop 012 stage f2
Body: traceback summary + "run `kf resume` to recover"
```

With this, the email channel covers all three event classes: **approvals, reports, failures**.

## 4. Data Backup (DP1)

- Images and full judge JSONs are already on OSS (naturally off-machine)
- The `data/` git repo pushes to a private remote at every batch boundary:

```json
{
  "paths": {
    "data_root": "./data",
    "data_remote": "git@github.com:you/keeper-factory-data.git"   // empty string = no push
  }
}
```

- Push failure is non-fatal: log a warning, include it in the batch report, retry at the next boundary. Knowledge assets are the system's most valuable output; a single machine disk must not be their only copy.

## 5. Runtime Environment

Pure Python + API calls (no GPU, no heavyweight libraries). Runs identically on macOS and Linux. v0 runs on the local Mac; moving to a server later requires zero code changes.

## 6. Runbook (first start)

1. `uv sync`
2. Fill `config.json`; export the 3 env vars (`KF_LLM_API_KEY`, `KF_OSS_AK`/`KF_OSS_SK`, `KF_MAIL_PASSWORD`)
3. `kf init` (creates the `data/` nested git repo and scaffolding; sets remote if `data_remote` is configured)
4. Place the 13 cases + `target_card.yaml` files under `data/goldenset/`
5. Run loop 0 warm-up (`kf run --loops 1 --warmup`); human-label the anchor set from its outputs
6. `kf run --loops N` - production loops begin

## 7. Open Items (deferred, tracked)

- Server migration checklist (env vars, tmux vs systemd) - post-MVP
- Optional `kf doctor` command (config/env/connectivity self-check) - nice-to-have during implementation
