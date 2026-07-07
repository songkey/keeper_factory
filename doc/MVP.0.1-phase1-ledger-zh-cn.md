# Keeper Factory MVP v0.1 - Phase 1：实验账本（C5 Ledger）设计

> 状态：已确认设计（第 2 阶段产物：组件详细设计）  
> 组件：C5 实验账本  
> 上级文档：`doc/MVP.0.1-base-zh-cn.md`  
> 定位：**Memory 存"提炼后的知识"，Ledger 存"发生过的事实"。**只追加、不修改，是全系统可归因、可复盘的物理基础。

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| LG1 | 记录粒度 | **1 个候选的一次执行+评判 = 1 条实验记录**；验证战役的每个样本各自 1 条 |
| LG2 | 产物存储 | **图片上传 OSS，URL 进 git。**OSS 配置写在 `config.json` |
| LG3 | 去重 | v0 只做**精确签名匹配**；语义近似去重延后 |
| LG4 | `execution_failure` 与 do-not-repeat | **豁免**——瞬时失败允许重试；只有被评判过的实验才进 DNR |
| LG5 | 预算 | **只记账，不做硬熔断**——loop 设计已有常数成本上界 |
| LG6 | judge_result 存储 | **完整裁判 JSON 上传 OSS、URL 内嵌**；记录内保留极小内联摘要（`verdict` + `failure_tags` + 各层分数）供高频消费方（F.4、去重索引、Report）使用 |

## 2. 目录结构

```
ledger/
  experiments/
    loop_012/
      exp_loop012_main_c1.json      # 一条实验一个 JSON 文件
      exp_loop012_val_s2.json
  loops/
    loop_012.json                   # loop 汇总（F.5 短摘要、停滞检查结果）
  batches/
    batch_003.json                  # 批次汇总（待审清单 + 人工回复结果）
  p1_versions/
    p1_v013.yaml                    # P.1 版本链（M6 的归属地）
    CURRENT                         # 当前生效版本指针
  reports/
    loop_012.md                     # 渲染后的 Report + 邮件发送状态
  signatures.jsonl                  # 去重索引（可由 experiments/ 全量重建）
  budget.jsonl                      # 每轮成本流水
```

以上全部是 git 管理的元数据。**二进制产物（结果图、edit prompt、裁判完整 JSON）存 OSS**；记录中携带 URL + sha256 校验值（防篡改、可校验）。

## 3. 实验记录 Schema（原子单元）

```json
{
  "exp_id": "loop012_main_c1",
  "exp_sig": "sha256:…",
  "loop": 12,
  "batch": 3,
  "kind": "main",                     // main / validation / probe / warmup
  "case_id": "case_003",
  "strategy": {
    "p1_version": "p1_v012",
    "candidate_index": 1,
    "declared_dimension": "light_shadow",
    "strategy_digest": "sha256:…",     // 策略描述的规范化 hash
    "injected_knowledge": ["pp_0003", "fn_0002"],
    "validates_recipe": null            // kind=validation 时填 cr_id
  },
  "env": {
    "vlm": "qwen-vl@x.y",
    "edit_model": "…@v2.1",
    "judge_model": "…@z",
    "p1_hash": "…",
    "redline_prompt_hash": "…",
    "quality_prompt_hash": "…",
    "dimension_vocab": "dimension_vocab_v0",
    "anchor_set": "anchor_v1"
  },
  "artifacts": {
    "edit_prompt_url": "oss://…/loop_012/exp_…/edit_prompt.txt",
    "result_image_url": "oss://…/loop_012/exp_…/result.jpg",
    "result_image_sha256": "…"
  },
  "judge_summary": {                  // 内联摘要，供高频消费方使用（LG6）
    "redline_pass": true,
    "verdict_vs_original": "better",
    "direction_score": 3,
    "execution_scores": {"realization": 3, "intensity": 2, "collateral_damage": 4},
    "failure_tags": ["over_saturation"]
  },
  "judge_result_url": "oss://…/loop_012/exp_…/judge_result.json",
  "status": "completed",              // completed / execution_failure / skipped_dnr
  "cost": {"vlm_calls": 5, "edit_calls": 1},
  "created_at": "2026-07-07T12:00:00+08:00"
}
```

内联摘要的理由（LG6 的工程适配）：F.4 归纳、去重索引、Report 渲染都高频消费裁决结论，每次回源 OSS 拉全文既慢又引入网络依赖；OSS 全文只在深度复盘时才需要。

## 4. 实验签名（`exp_sig`）与去重规则

签名 = 对以下字段的规范化 JSON 取 sha256：

```
case_id + declared_dimension + strategy_digest
+ injected_knowledge（排序后）+ env 全部字段
```

注意：**`loop` 与 `candidate_index` 不参与签名**——签名标识的是"语义上同一个实验"，与何时执行无关。

Do-not-repeat 规则：

- v0 只做**精确匹配**（LG3）：新候选签名已存在于 `signatures.jsonl` → 丢弃并补位（依据 C3，至多补一轮）
- **`execution_failure` 的签名不进 DNR**（LG4）——失败可能是瞬时的；只有被评判过的实验（无论裁决好坏）才进入
- `signatures.jsonl` 行格式：`{"sig": "…", "exp_id": "…", "verdict": "…", "loop": 12}`；丢失可从 `experiments/` 全量重建

## 5. P.1 版本链

```yaml
# p1_versions/p1_v013.yaml
version: p1_v013
parent: p1_v012
created_loop: 12
slot_diffs:
  - slot: constraints
    before_hash: "…"
    after_hash: "…"
    diff_text: "…"
rationale: "本轮证据显示多指令导致全图重绘，收紧为单指令"
refine_exp_ref: loop012_refine       # 产出该 diff 的 P.4_refine 调用记录
```

- 当前生效版本由 `p1_versions/CURRENT` 指针文件引用
- 回滚 = 把 `CURRENT` 指向任意历史版本，天然支持

## 6. 预算：只记账（LG5）

- `budget.jsonl` 每轮一行：各类调用数、与理论上界（~36 次 VLM / 6 次 edit）的偏差
- v0 不做硬熔断——loop 已有常数上界，此时加熔断属于过度工程
- 每期批次 Report 中呈现累计成本

## 7. config.json（oss 段）

```json
{
  "oss": {
    "endpoint": "…",
    "bucket": "…",
    "prefix": "keeper_factory/mvp01",
    "access_key_env": "KF_OSS_AK",
    "secret_key_env": "KF_OSS_SK"
  }
}
```

安全说明：凭证**引用环境变量名**，绝不直接写值——`config.json` 会提交进 git，明文密钥入库是安全事故。

## 8. 遗留事项（延后处理，持续跟踪）

- OSS 服务商 / SDK 选型与上传重试策略——第 3 阶段（开发/部署）议题
- `reports/` 是否归档邮件完整内容，还是只存发送状态 + 内容 hash（倾向存完整内容；成本低且自包含）
- 签名的语义近似去重（embedding 相似度）——MVP 之后
- loop 数量增大后的 Ledger 压缩/归档策略——MVP 之后
