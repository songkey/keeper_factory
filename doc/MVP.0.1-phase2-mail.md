# Keeper Factory MVP v0.1 - Phase 2: Email Channel

> Status: Confirmed design (Stage 3 output: development/deployment details, item 3)  
> Parent doc: `doc/MVP.0.1-phase2-stack.md`  
> Protocol semantics defined in `doc/MVP.0.1-phase1-memory.md` (Section 5); this doc covers the implementation.

---

## 1. Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| MC1 | Reply matching | **Subject token + sender whitelist**; no reply passphrase in v0 |
| MC2 | Application semantics | **Partial application**: valid lines take effect immediately; invalid lines are summarized in an error/confirmation email; remaining items keep waiting. Reply commands simplified for mobile mail clients |
| MC3 | Batch shortcut | **`all ok` supported; no `all no`** (bulk-reject is too risky for a one-line reply) |
| MC4 | Reminder & timeout | Reminder every **1 hour** (configurable, `mail.reminder_hours`, fractional allowed); **never auto-approve** |

## 2. Sending (SMTP, stdlib)

- Per-loop Reports and batch-end review lists are sent as multipart mail: plain text + simple HTML (rendered from markdown)
- **Result images are embedded via OSS public URLs** - the approver compares images directly in the mail client, no machine login needed
- Subject carries a routing token: `[KF][loop 012] Report`, `[KF][batch 003] Review required`. The token anchors reply matching
- The batch review mail body lists every pending item: sequence number, type, principle summary, evidence image URL pairs, and the reply guide

## 3. Receiving (IMAP polling, stdlib)

- **Polling only while waiting at a batch boundary** (default interval 300s); no polling otherwise - avoids a resident listener
- Match rule: subject contains the batch token **AND** sender is in the approver whitelist; anything else is ignored (v0 security boundary)

## 4. Simplified Reply Protocol (MC2)

Core idea: **items are numbered in the review email; replies use number + short word**. No knowledge ids needed on a phone.

### Review email body example

```
[KF][batch 003] Review required (3 knowledge items + 1 conflict)

-- Pending knowledge --
1. [Pattern Patch] pp_0012 "Backlit portrait: freeze identity first, then develop subject lighting"
   Evidence: original vs result https://oss…/a.jpg https://oss…/b.jpg
2. [Failure Note] fn_0005 "Multi-instruction prompts cause full repaint"
3. [Capability Note] cn_0003 "Edit model cannot brighten locally without color-temperature shift"

-- Conflict resolution --
4. pp_0012 and pp_0009 overlap in scope with contradictory advice
   4a = merge    4b = keep pp_0012    4c = keep pp_0009

-- How to reply (reply directly to this email) --
One decision per line:
  1 ok        (approve)
  2 no        (reject)
  3 hold      (dispute, schedule re-validation)
  4a          (conflict: reply the option code)
Approve everything remaining with a single line: all ok
```

### Parsing rules

- Short-word aliases: `ok` = approve (also `yes` / `通过`), `no` = reject (also `拒绝`), `hold` = dispute (also `?` / `存疑`)
- Conflict items: reply the option code (`4a` / `4b` / `4c`); the code IS the decision
- `all ok` = approve all remaining unresolved items (**no `all no`**, per MC3)
- The number -> knowledge-id mapping is stored in the batch summary record (`batches/batch_003.json`); the parser translates via it. Verbose form (`pp_0012: approve`) remains supported as a precise fallback
- Case, extra whitespace, and quoted text (`>` lines and everything after the original-message marker) are tolerated/stripped
- Invalid lines (unknown number, malformed) follow partial application: a confirmation email lists applied items + errored lines; waiting continues for the rest

## 5. Timeout Policy (MC4)

- **Never auto-approve** - approval is a safety mechanism; timeout-passing would nullify it
- No reply within `mail.reminder_hours` (default 1h) -> send a reminder; repeat every interval; wait indefinitely
- Fallback: the `kf approve` local command is always available and **routes through the same parser code path** - this guarantees the future UI backend reuses identical semantics

## 6. config.json (`mail` section)

```json
{
  "mail": {
    "smtp_host": "…", "smtp_port": 465,
    "imap_host": "…", "imap_port": 993,
    "username": "…", "password_env": "KF_MAIL_PASSWORD",
    "from": "keeper-factory@…",
    "approvers": ["you@…"],
    "poll_interval_seconds": 300,
    "reminder_hours": 1
  }
}
```

## 7. Open Items (deferred, tracked)

- HTML template polish (v0 ships minimal markdown-to-HTML)
- Multi-approver conflict rule (v0 assumes a single approver in practice; first-valid-reply-wins if several)
- Webhook-based receiving (replaces IMAP polling when a mail service is introduced; parser unchanged)
