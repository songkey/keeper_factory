# Keeper Factory MVP v0.1 - Phase 2：config.json 全量 Schema

> 状态：已确认设计（第 3 阶段产物：开发/部署细节，第 5 项）  
> 上级文档：`doc/MVP.0.1-phase2-stack-zh-cn.md`  
> 本文档是散落在各组件设计中的 config 字段的唯一收拢点，各段均标注来源。

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| CF1 | T0 位置 | **`prompts/t0.txt`**——与其他人工维护的提示词资产同级，进代码仓 git，加载时 hash 进实验签名 |
| CF2 | 晋级阈值 | k=3 与 worse 率 25%（judge-spec 的"可调初值"）**提升为 config 字段**（`promotion` 段） |
| CF3 | 日志位置 | **`data/ledger/logs/`**——数据仓内（gitignore），日志与运行数据同处一地，方便复盘 |

## 2. 全量 Schema

```json
{
  "paths": {
    "data_root": "./data",                // 独立嵌套 git 仓库（S3）
    "data_remote": ""                     // 批次边界自动 push 的远端；为空则不 push（DP1）
  },

  "loop": {                               // 来源：C3
    "batch_size": 5,                      // 每批轮数（M1 审批边界）
    "candidate_num": 3,                   // N，每轮候选数（L1）
    "context_window": 3,                  // F.1 注入的近期摘要数（L5）
    "stagnation_threshold": 3             // m，停滞标记阈值（L6）
  },

  "memory": {                             // 来源：C2
    "case_recipe_ttl": 5,                 // M2
    "max_injection_num": 3                // M5
  },

  "promotion": {                          // 来源：judge-spec 第 6 节（CF2）
    "min_samples": 3,                     // k：二次验证最少样本数
    "worse_rate_max": 0.25                // worse 率上限
  },

  "models": {                             // 来源：model-layer（ML2）
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

  "oss": {                                // 来源：C5（LG2）
    "endpoint": "…",
    "bucket": "…",
    "prefix": "keeper_factory/mvp01",
    "access_key_env": "KF_OSS_AK",
    "secret_key_env": "KF_OSS_SK"
  },

  "mail": {                               // 来源：邮件通道（MC1-MC4）
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
    "file": "ledger/logs/kf.log"          // 相对 data_root；loguru 滚动日志，gitignore（CF3）
  }
}
```

## 3. 加载规则（pydantic 实现）

- 所有 `*_env` 字段在加载时解析环境变量；缺失**立即启动失败**（fail fast）
- 凭证绝不以明文值写入 `config.json`（该文件进 git）
- 加载后整个 config 的规范化 hash 即 checkpoint 使用的 `config_hash`（CK2）；提示词文件（含 `prompts/t0.txt`，CF1）单独 hash 为 `prompts_hash`
- 未知字段拒绝加载（pydantic `extra="forbid"`）——可捕获节点名拼写错误之类的笔误

## 4. 环境变量汇总

| 变量 | 使用方 |
|---|---|
| `KF_LLM_API_KEY` | models.api |
| `KF_OSS_AK` / `KF_OSS_SK` | oss |
| `KF_MAIL_PASSWORD` | mail |

## 5. 遗留事项（延后处理，持续跟踪）

- 仓库随附 `config.example.json` 模板；真实 `config.json` 若含机器相关（非机密）值可考虑 gitignore（实现时定）
