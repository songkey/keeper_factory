# Keeper Factory MVP v0.1 - Phase 1：主循环（C3 Loop）设计

> 状态：已确认设计（第 2 阶段产物：组件详细设计）  
> 组件：C3 主循环  
> 上级文档：`doc/MVP.0.1-base-zh-cn.md`  
> 依赖（均已定型）：C1 Golden Set（`MVP.0.1-phase1-goldenset-zh-cn.md`）、C2 Memory（`MVP.0.1-phase1-memory-zh-cn.md`）、C4 Judge Spec（`MVP.0.1-phase1-judge-spec-zh-cn.md`）

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| L1 | 每轮主实验候选数（N） | `config.json` -> `loop.candidate_num`，**默认 3** |
| L2 | 验证预算 | **每轮至多 1 次验证战役**；临时区靠 TTL 自然淘汰排队项 |
| L3 | P.1 精修提示词 | **新增 `P.4_refine`**：独立的、人工定义的固定元提示词，与 `P.4_synthesis` 分开 |
| L4 | 同源 recipe 处理 | 仅 pairwise **第一名**候选的 recipe 进入临时区 |
| L5 | 前轮上下文 | 最近若干轮的结构化短摘要，`config.json` -> `loop.context_window`，**默认 3** |
| L6 | 停滞阈值（m） | `config.json` -> `loop.stagnation_threshold`，**默认 3** |
| L7 | 候选间 pairwise | v0 **保留**（跑几个批次有数据后再评估是否砍掉） |

## 2. Loop 形态：一轮 = 一次主实验 + 至多一次验证战役

若每轮立即验证所有有价值的 recipe，单轮成本会爆炸。因此：

- **主实验**：确定性轮换选 1 个主样本，生成并评判 N 个候选
- **验证战役**：每轮**至多验证 1 条** Case Recipe（临时区中价值最高的 pending 项），在 k=3 个同类样本上执行
- 排不上队的 recipe 由 TTL（5 轮）自然过期——这正是 TTL 机制的真正意义：验证带宽有限，队列自清洁

结果：单轮成本有**常数上界**，预算可预测。

## 3. 五步详细定义

### F.1 采样 + 候选生成

1. **主样本选择**：类别按 `bad -> bad -> good -> redline` 轮换（G4）；类别内取"最久未被抽中"的 case
2. **上下文组装**：`T0` + Memory 注入（按 C2 读路径规则）+ **最近 `loop.context_window` 轮的结构化短摘要**（不是完整 Report）+ 当前 P.1 版本
3. **单次调用生成 N 个候选**：一次 P.1 调用产出 N 个差异化策略（而非 N 次独立调用）。多样性在提示词中显式要求（"N 个策略必须在探索维度或控制结构上互异"），同时便于去重
4. 每个候选生成实验签名；命中 do-not-repeat 的候选丢弃并要求补位（**至多补一轮**）

每个候选必须显式声明：`declared_dimension`（封闭词表）+ 策略描述 + 给 edit model 的方案骨架。

### F.2 执行

- 每个候选：VLM 生成 edit prompt -> edit model 出图
- 失败处理：**单次重试**；再失败记为 `execution_failure`（进 Ledger，不进裁判），不补位
- 全部中间产物（edit prompt、结果图、模型参数）落盘归档，路径写入实验签名

### F.3 评判

- 按 Judge Spec 执行：Call-1 红线 -> Call-2 质量 + pairwise（vs 原图双向、候选间双向；L7 保留候选间）
- 每个存活候选产出一份 Case Recipe 草稿，`validation_state: pending`
- **同一主样本的 N 个候选，仅 pairwise 第一名的 recipe 进入临时区**（L4）；其余仅记 Ledger——防止临时区被同源策略灌满

### F.4 验证 + 归纳 + P.1 演进（三个子步骤）

- **F.4a 验证战役**：从临时区取价值最高的 pending recipe（排序依据：主实验裁决为 better、Layer 2 分高、scope 覆盖广），在同类别 k=3 样本上执行 F.2+F.3，按类别感知计分表算总分
- **F.4b 归纳**：`P.4_synthesis` 决定晋级 / 抛弃 / 转 Failure Note 或 Capability Note；写 Memory（单一写入者规则在此执行）
- **F.4c P.1 精修**：独立固定元提示词 **`P.4_refine`** 输入本轮全部证据，输出 P.1 的**槽位 diff 提案**（≤3 个槽位）。新版本记 `p1_v{i+1}`，下轮生效。P.1 版本链存 Ledger（M6）

拆分 `P.4_synthesis` 与 `P.4_refine` 的理由（与 P.3 拆分相同）：知识归纳与探索策略调整是两种职责，混入一次调用会污染归因。

### F.5 Report

标准结构（已定）：本轮假设 -> 实验矩阵 -> 结果分布 -> 升级/降级/淘汰知识 -> 下轮计划。另加：

- **结构化短摘要**（约 10 行），供后续轮次 F.1 消费（即 L5 所指内容）
- **停滞检查**：
  - 主指标连续 `loop.stagnation_threshold` 轮无提升 -> Report 标红"建议策略级改写"，批末交人工
  - bad case 提升但 good case 回归 -> 下轮强制变为 good case 保护轮
- 邮件发送（每轮信息性；批末阻塞待审）

## 4. 单轮成本预算（N=3、k=3 时的上界）

| 环节 | VLM 调用 | edit model 调用 |
|---|---|---|
| F.1 候选生成 | 1 | 0 |
| F.2 主实验 | 3（edit prompt） | 3 |
| F.3 主实验评判 | 3 红线 + 3 质量 + ~9 双向 pairwise | 0 |
| F.4a 验证战役 | 3 + 3 红线 + 3 质量 + 6 pairwise | 3 |
| F.4b/c 归纳 + 精修 | 2 | 0 |
| **合计上界** | **~36** | **6** |

单机完全可承受。若需降本，优先砍候选间 pairwise（约 9 次调用），用 Layer 2 分数排序替代——依据 L7，等有真实批次数据后再定。

## 5. config.json（loop 字段汇总）

```json
{
  "loop": {
    "batch_size": 5,
    "candidate_num": 3,
    "context_window": 3,
    "stagnation_threshold": 3
  }
}
```

| 字段 | 含义 | 默认值 |
|---|---|---|
| `batch_size` | 每批轮数（M1，晋级审批边界） | 5 |
| `candidate_num` | N，每轮主实验候选数 | 3 |
| `context_window` | F.1 注入的近期 loop 摘要数量 | 3 |
| `stagnation_threshold` | m，连续无提升多少轮后标记策略改写 | 3 |

## 6. 遗留事项（延后处理，持续跟踪）

- Loop 状态检查点 / 崩溃恢复（按 F 步骤落盘 checkpoint）——第 3 阶段议题
- F.4a 的 recipe 价值排序公式细化（初值：裁决 > Layer 2 总分 > scope 广度；有数据后调优）
- good case 保护轮（停滞触发 2）当轮是否同时暂停验证战役（倾向暂停，保持成本上界）
