# Keeper Factory MVP v0.1 - Phase 1：Golden Set 与 Target Card 规格

> 状态：已确认设计（第 2 阶段产物：组件详细设计）  
> 组件：C1 Golden Set（测试集）  
> 上级文档：`doc/MVP.0.1-base-zh-cn.md`  
> 关联文档：`doc/MVP.0.1-phase1-judge-spec-zh-cn.md`（本文档了结其遗留事项 3，并修订其第 6 节）

---

## 1. 集合构成（v0）

| 项目 | 数值 |
|---|---|
| 原图总数 | 13 张 |
| bad case | 5 张（验证能否把问题图推向目标） |
| good case | 5 张（验证克制；防回归） |
| redline case | 3 张（验证硬约束是否守住） |
| 专业精修参考图 | **v0 无**——纯文本标注 |

“无参考图”的连带影响：

1. 裁判 Call-2 没有 `Original -> Reference` 的改善方向可比对；方向/执行判断完全依赖 `candidate_dimensions + hint`。因此 **hint 的质量从可选加分项升级为关键输入**。
2. 裁判锚定集无法来自精修参考，改由预热 loop 构建（见第 6 节）。
3. Pattern Patch 的归纳完全依赖裁判裁决 + 人工 hint。作为 MVP 简化予以接受。

## 2. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| G1 | `hint` 是否必填 | **bad case 必填**；good/redline 可选 |
| G2 | `scene_brief` 是否给 F.1 看 | **不给。** F.1/F.2 完全自主看图；所有标注仅服务裁判 |
| G3 | 计分方式 | **类别感知计分**（见第 5 节；修订 judge-spec 第 6 节） |
| G4 | v0 采样策略 | **确定性轮换**替代课程化采样比例（见第 7 节） |

## 3. 目录结构

```
goldenset/
  case_001/
    original.jpg
    target_card.yaml
  case_002/
    …
```

## 4. Target Card Schema（`target_card.yaml`）

```yaml
case_id: case_001
category: bad                    # bad / good / redline
scene_brief: "黄昏海边逆光人像，主体偏暗，天空过曝"

# ── 仅裁判可见（D5：绝不进入 F.1/F.2 上下文）──
candidate_dimensions:            # 1-3 项，封闭词表（dimension_vocab_v0）
  - dimension: light_shadow
    hint: "压暗过曝天空、提亮主体，强化黄昏侧光氛围"   # bad 必填
must_keep:
  - "人物身份特征与姿态"
  - "海面与天空的自然衔接"
forbidden:
  - "添加原图不存在的物体"
  - "改变天气或时间设定"

# ── 类别专属字段（三选一）──
problem_note: "主体欠曝导致表现力弱，天空高光溢出"        # bad
# established_note: "…"   # good：已成立价值的描述（裁判评"克制"的依据）
# trap_note: "…"          # redline：本 case 考察哪条红线、什么算踩线
```

可见性规则：

- **Target Card 的全部内容仅裁判可见。**依据 G2，连 `scene_brief` 也不给 F.1（它的用途是人工消歧与裁判上下文）。
- F.1/F.2 只接收原图（以及 base 文档定义的 T0 / Memory / loop 上下文）。

## 5. 三类样本的标注要求与计分

### 标注要求

| 类别 | 必填字段 | 说明 |
|---|---|---|
| bad | `candidate_dimensions`（`hint` 必填）、`must_keep`、`forbidden`、`problem_note` | hint 写清期望的发展方向 |
| good | `candidate_dimensions`（hint 可选）、`must_keep`、`forbidden`、`established_note` | `established_note` 是裁判评"该不该动"的依据 |
| redline | `must_keep`、`forbidden`、`trap_note`（hint 可选） | 3 张分别覆盖不同陷阱：身份（清晰人脸）、事实（文字/标志）、场景（复杂光影逻辑） |

### 类别感知计分（修订 judge-spec 第 6 节）

统一的 `same = 0` 是为度量 bad case 的提升而设计的。对 good case，`same` 本身就是成功（克制）；对 redline case，`pass` 就是成功。否则 good case 永远无法贡献正分，采样器会误判其无价值。

| 类别 | 成功判据 | 计分 |
|---|---|---|
| bad | better | better = +1 / same = 0 / worse = -1 / redline fail = -2 |
| good | same 或 better | same = +1 / better = +1 / worse = **-2**（回归罪加一等） |
| redline | redline pass | pass = +1 / fail = **-3**（底线，惩罚最重） |

## 6. 预热 Loop（loop 0）与裁判锚定集

由于没有精修参考图，裁判锚定集通过预热轮构建：

1. 用初版 P.1 对若干 case 跑一次 F.1/F.2 产出 candidate（不晋级、不写 Memory）
2. 人工为每组 (original, candidate) 标定期望裁决（如适用附 violation 说明）
3. 选取 5-10 组标定样例，作为 few-shot 锚点嵌入 P.3_eval 的 rubric
4. 锚定集版本化，版本号写入实验签名

loop 0 的产出不计入任何统计与知识沉淀。

## 7. 小样本风险与对策

| 风险 | 对策 |
|---|---|
| **验证耗尽**：k=3 的二次验证在 5 张 bad case 中不可避免地复用"发现样本"做"验证样本" | MVP 阶段接受。所有 Pattern Patch 封顶为 `status: candidate`，scope 注明"在 13 张集合上成立"；升 `active` 必须等扩集 |
| **课程化采样在 n=13 上无统计意义** | v0 降级为**确定性轮换**：每轮主实验样本按 bad -> bad -> good -> redline 轮转；F.4 二次验证抽同类样本。完整课程化采样器待扩集后恢复 |

## 8. 遗留事项（延后处理，持续跟踪）

- 13 张原图的具体选片（人工筹备中：5/5/3）
- 锚定集的目标规模，以及裁判模型换版本后的刷新策略
- 扩集触发条件：何时超出 13 张（建议：MVP 验收标准通过后）
