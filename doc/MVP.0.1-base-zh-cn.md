# Keeper Factory MVP v0.1 - 基础设计

> 状态：讨论稿（第 1 阶段产物：整体逻辑框架）  
> 范围：仅定义组件、协作关系与循环演进方式，不涉及实现细节  
> 上游文档：《Keeper Factory 总纲 v0.1》《Keeper Factory 系统设计 v0.1》《Keeper Factory Lab v0.1》

---

## 1. 定位与边界

Keeper Factory MVP 是一个与 Runtime 完全隔离的实验室（Lab）。要验证的核心命题是：

> 在目标意图（T0）、Golden Set 以及禁止边界由人工定义清楚的前提下，  
> 系统能否通过自循环实验自动生成候选策略、比较结果差距、迭代失败点，  
> 并沉淀出可跨 case 复用的资产：Pattern Patch / Failure Note / Capability Note。

**本版本明确不做：**

- 不接入 Runtime，不做灰度或 Shadow 对比（这是 MVP 通过后的下一阶段）
- 不追求完全无人值守；人工仍负责目标定义、裁判协议和周期性校准
- 不把降本作为目标；成本是约束，结果质量与知识生产才是目标

## 2. 处理管线（被优化对象）

```
原图 -> VLM（分析 + 生成编辑方案）-> edit prompt -> Image Edit Model -> 编辑结果
```

- VLM 的 system/user prompt 质量是关键判断知识（J1）
- Image Edit Model 的 prompt 写法知识为 J1_edit，主要沉淀在 Capability Note

## 3. 总体目标 T0

T0 是人工撰写的一段文本，用于定义什么是“图像成立”的结果，是系统收敛的唯一北极星。

- T0 由人工维护，不自动演进
- Judge、归纳和报告都必须与 T0 对齐
- T0 的变更属于大版本事件，需要全量回归

## 4. 组件总览

| 组件 | 职责 | 演进方式 |
|---|---|---|
| C1 测试集（Golden Set） | 提供稳定、可重复、目标清晰的实验场 | 人工维护，缓慢扩充 |
| C2 记忆（Memory） | 存储四类知识及其生命周期状态 | 由 loop 自动更新，人工周期审计 |
| C3 主循环（Loop） | 执行 假设 -> 实验 -> 评估 -> 验证 -> 沉淀 | 核心提示词 P.1 随轮次演进 |
| C4 裁判协议（Judge Spec） | 定义 better/same/worse 与红线硬门槛 | 人工定义，不自动演进 |
| C5 实验账本（Ledger） | 实验签名、去重、预算、报告归档 | 系统自动记录 |

> **v0 人机交互通道（依据 Memory 设计补充）**：每轮 loop 结束后 Report 通过邮件发送；批次边界的审批（知识晋级复核、冲突裁决）通过邮件回复结构化文本完成。后续 UI 后台仅替换通道载体，协议语义不变。详见 `doc/MVP.0.1-phase1-memory-zh-cn.md`。

### 4.1 C1 测试集（Golden Set）

每个 case 至少包含：原图、Target Card（目标期待、必须保留项、禁止项）、可选的专业精修参考图。

样本必须包含三类：

- **bad case**：验证是否能把问题图推向目标（测上限提升）
- **good case**：验证是否克制，不把已成立图片修坏（防回归）
- **redline case**：验证身份、事实、场景真实性等硬约束（守底线）

### 4.2 C2 记忆（知识体系）

| 编号 | 名称 | 性质 | 作用 |
|---|---|---|---|
| K.1 | Case Recipe | **临时**、绑定单 case | 实验中间产物，等待二次验证 |
| K.2 | Pattern Patch | 可泛化到一类 case 的通用知识 | 上限保障，是上线候选资产 |
| K.3 | Failure Note | 可泛化的负优化知识 | 下限保障 |
| K.4 | Capability Note | VLM / Edit Model 的能力边界与优势知识 | 促进 K.2 / K.3 演进 |

每条知识的通用字段：

- `scope`：适用边界（图像类型、场景、拍法等）
- `confidence`：置信度（由重复验证更新）
- `evidence`：支持该知识的实验签名
- `status`：candidate / active / deprecated

晋级门槛（量化，避免记忆污染）：

| 路径 | 条件 |
|---|---|
| Case Recipe -> Pattern Patch | 在 >= k 个不同子类上显著正收益，且 redline 通过率不下降、good case 不回归 |
| Case Recipe -> Failure Note | 同类负优化在多个样本上重复出现（>=2 次独立复现） |
| Observation -> Capability Note | 模型行为可被 >=2 次独立实验复现 |
| 任意 -> discard | 在后续回归中失效，或被更高置信知识覆盖 |

### 4.3 C3 主循环（Loop）

第 i 轮（记作 `c{i}`）：

```
F.1.c{i} 采样 + 生成 N 个候选方案
         输入：T0 | Memory | 前 n 轮上下文
         输出：N 组 VLM prompt 变体（受约束改动）
        ->
F.2.c{i} 执行：VLM -> edit prompt -> Image Edit -> N 个结果
        ->
F.3.c{i} 评估：按 Judge Spec 对原图/参考图/候选图进行比较
         输出：结构化 Case Recipe（评分 + 证据 + 失败标签）
        ->
F.4.c{i} 验证与归纳：
         a) 选取高价值 Case Recipe，抽更多样本做二次验证
         b) 达标后升级为 Pattern Patch / Failure Note / Capability Note，并更新 Memory
         c) 修正 P.1，使下一轮更靠近 T0 收敛方向
        ->
F.5.c{i} Report：按标准模板总结本轮得失
```

采样策略（课程化采样，替代纯随机）：

- 40%：高不确定性 / 最近波动大的 case（提升学习效率）
- 30%：历史失败簇（修复下限）
- 20%：good case 回归保护（稳定性）
- 10%：随机探索（避免局部最优）

F.5 报告标准结构：

```
本轮假设 -> 实验矩阵 -> 结果分布 -> 升级/降级/淘汰的知识 -> 下一轮计划
```

### 4.4 C4 裁判协议（Judge Spec）

必须在 F.3 之前固定，由人工定义，不自动演进：

- 固定评分维度：目标达成度、身份一致性、场景真实性、伪影、风格一致性等
- 每个维度定义 hard-fail 条件（任一 hard-fail 直接判负，再不进入加权评分）
- 输出结构化 JSON：分数 + 证据 + 失败类型标签
- 参考图使用原则：比较 Original -> Reference 的关键改善方向是否在 Candidate 中实现，不做像素级对齐

### 4.5 C5 实验账本（Ledger）

- 每个实验记录 `experiment_signature`：模型版本 + 提示词模板 hash + 关键参数 + case 簇
- Do-not-repeat：命中历史低价值签名时跳过或降权
- 记录预算与“去重节省量”，并写入报告

## 5. 提示词体系

| 编号 | 所在环节 | 演进方式 |
|---|---|---|
| P.1.c{i} | F.1 候选生成 | **核心演进对象**，受约束搜索 |
| - | F.2 | 无独立提示词（edit prompt 由 VLM 生成） |
| P.3_eval | F.3 评估 / 生成 Case Recipe | 人工定义，固定不演进 |
| P.4_synthesis | F.4 跨样本归纳与晋级判断 | 半固定，可弱演进（需人工审核） |

P.1 演进规则（Prompt as Policy，受约束搜索）：

- 使用参数化模板：目标段 / 约束段 / 优先级段 / 输出结构段
- 每轮最多改 2-3 个槽位
- 每次改动都记录：diff + 修改理由 + 关联实验签名（可追溯、可回滚、可归因）

为何拆分 P.3_eval 和 P.4_synthesis：

- 评估需要稳定，保证跨轮可比较
- 归纳可以演进（但必须有人类审核）

## 6. 探索治理：停滞触发器

| 信号 | 动作 |
|---|---|
| 主指标连续 m 轮无提升 | 从细节调参升级到策略级改写 |
| bad case 提升但 good case 回归 | 进入保护模式，先修回归 |
| redline 失败超过阈值 | 冻结当前候选族，转入能力边界探测 |
| 多组 P.1 变体均无效 | 怀疑根因不在提示词层，转查 plan/原则/模型能力边界 |

## 7. MVP 验收标准

1. **闭环可重复**：同一 case 的实验可复现、可比较、可复盘
2. **知识可沉淀**：至少产出 1 条经二次验证的 Pattern Patch，及若干 Failure/Capability Note
3. **失败可归因**：失败实验输出明确失败原因，而不只是结果图
4. **无回归**：演进过程中 good case 与 redline case 保持稳定
5. **提示词可追踪**：每次 P.1 演进都有 diff、理由、证据链

## 8. MVP 之后的方向（本版范围外）

扩展 Golden Set -> 引入 Shadow 对比（同输入下对比 Runtime/人工 vs Factory）-> 持续证明可靠后再进入 Runtime Candidate。
