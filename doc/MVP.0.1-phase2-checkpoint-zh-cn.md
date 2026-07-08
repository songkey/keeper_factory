# Keeper Factory MVP v0.1 - Phase 2：Checkpoint 与崩溃恢复

> 状态：已确认设计（第 3 阶段产物：开发/部署细节，第 4 项）  
> 上级文档：`doc/MVP.0.1-phase2-stack-zh-cn.md`

---

## 0. 前提

按现有设计，绝大部分状态本来就实时落盘（只追加的 Ledger、YAML 的 Memory、可重建的签名索引、P.1 的 `CURRENT` 指针、批次汇总记录）。checkpoint 只需覆盖**一轮进行中的飞行状态**，不需要重型方案。

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| CK1 | checkpoint 粒度 | **F 步骤级**，在 F.2 与 F.4a 内部**细化到每个候选/样本**（烧 edit 调用的两步） |
| CK2 | 恢复时配置/提示词漂移 | checkpoint 存 config + prompts 的 hash；恢复时不一致 -> **默认拒绝**，`kf resume --force` 显式覆盖 |
| CK3 | 崩溃时的在途执行 | **重新执行**（接受一次重复 API 成本，换取归因干净：磁盘无记录 = 没发生过） |

## 2. Checkpoint 文件

单文件 `ledger/checkpoint.json`，**临时文件写入 + 原子 rename**：

```json
{
  "loop": 12,
  "batch": 3,
  "stage": "f2",                       // f1 / f2 / f3 / f4a / f4b / f4c / f5 / batch_wait
  "inflight": {
    "main_case_id": "case_003",
    "candidates_total": 3,
    "candidates_done": ["loop012_main_c1"],   // 已写入实验记录的
    "validating_recipe": null
  },
  "config_hash": "…",
  "prompts_hash": "…",
  "updated_at": "…"
}
```

## 3. 写入时机（CK1）

- 每个 F 步骤完成后写一次
- **F.2 与 F.4a 内部**：每完成一个候选/样本的执行 + 记录写入就写一次——细粒度使恢复时浪费的 edit 调用最少
- 全部 Ledger/Memory 写入统一走临时文件 + rename（原子）；实验记录先写、签名索引后更；恢复时以实验记录为事实源，索引可重建

## 4. 恢复语义（`kf resume`）

1. **修复轮**：data 仓库 dirty（崩溃落在 Memory 写入与 git commit 之间）-> 自动补 commit（message 为 `recovery: loop N`）；再校验 checkpoint 引用的实验记录都存在
2. **重入当前 stage**：已有实验记录的候选/样本直接跳过；执行到一半没出记录的候选**重新执行**（CK3——崩溃时在途的 API 调用视为丢失）
3. **`batch_wait` 阶段**：检查批次记录中"待审邮件已发送"标记；已发则只恢复轮询（提醒计时重新起算）；未发则补发

## 5. 一致性保护

- **配置/提示词漂移拦截（CK2）**：hash 不一致 -> 拒绝并给出说明；`--force` 覆盖。理由：跑到一半换 P.3 提示词会使同一轮内的裁判不可比
- **单实例锁**：`ledger/.lock`（含 pid），防止两个进程并发写；死锁文件（pid 已不存在）回收并告警

## 6. 明确不做的

- 不做"半个 LLM 调用"的续传（在途调用直接重发）
- 不做多机/分布式恢复（单机 MVP）

## 7. 遗留事项（延后处理，持续跟踪）

- 被重跑候选留下的 OSS 孤儿产物（无害；MVP 后可选清理任务）
- loop 结构演进时的 checkpoint schema 版本化
