# Keeper Factory MVP v0.1 - Phase 1：裁判协议（Judge Spec）

> 状态：已确认设计（第 2 阶段产物：组件详细设计）  
> 组件：C4 裁判协议  
> 上级文档：`doc/MVP.0.1-base-zh-cn.md`  
> Judge Spec 由人工定义，**不自动演进**。本协议的任何变更都会破坏跨轮评分可比性，必须版本化管理。

---

## 0. 背景：T0 及其对裁判的影响

当前 T0（极简版）：

> 寻找这张照片最有潜力的维度，发展它使之成为最终摄影作品。

T0 是一个**开放式、发散型目标**：没有唯一正确答案，同一张照片可能有多个成立的发展方向。由此产生两个直接推论：

1. 裁判必须**分开评两件事**，因为二者的失败归因完全不同：
   - **方向判断**：系统选中的维度是不是真正值得发展的维度？（失败 = 价值发现层的问题）
   - **执行判断**：沿该维度的发展是否真的实现，且到位不过火？（失败 = Plan / edit prompt / 模型能力的问题）
2. **红线独立于以上两层**。无论方向多惊艳、执行多到位，身份漂移、场景失真、伪影都是一票否决。这针对"发展潜力"最常见的失败模式：为戏剧化效果牺牲真实性。

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| D1 | 潜力维度由谁定义？ | **(a)** Target Card 中人工预标 1-3 个候选维度；裁判据此评命中与质量 |
| D2 | 裁判单次调用还是拆分？ | **两次调用**：先红线判定，通过后才做质量评判 |
| D3 | 维度词表 | **封闭词表 + `other` 逃生口** |
| D4 | `same` 裁决的计分 | **same = 0**，不算正收益 |
| D5 | F.1（候选生成）能否看到 `candidate_dimensions`？ | **不给看（保密）**。系统必须自己发现维度；人工预标仅作为裁判的对答案依据 |
| D6 | 双向 pairwise 对比（成本翻倍） | **接受**。A-vs-B 与 B-vs-A 各做一次；结果不一致记 `same` |

## 2. Target Card 字段变更（对 C1 的接口要求）

每个 Golden Case 新增必填字段：

```yaml
candidate_dimensions:            # 1-3 项，取自封闭词表（见第 4 节）
  - dimension: light_shadow
    hint: "黄昏侧光值得强化"      # 可选，仅裁判可见
  - dimension: atmosphere
    hint: null
```

可见性规则：

- `candidate_dimensions` 与 `hint` **仅裁判（Call-2）可见**
- **绝不**注入 F.1 / F.2 的上下文（依据 D5）。泄露给上游等于把价值发现测试变成喂答案。

## 3. 裁判结构：四层

### Layer 0 - 红线门（hard fail，先于一切评分）

任一命中即判 `fail`，该 candidate 不进入 pairwise 排序。violations 仍写入 Case Recipe（Failure Note 的原料）。

| 红线 | 判定要点 |
|---|---|
| 身份一致性 | 人脸、体型、发型等身份特征不可漂移 |
| 事实性 | 不可增删改会改变事实的物体、文字、人物 |
| 场景真实性 | 光影逻辑、透视、材质不可违背物理直觉 |
| 伪影 | 明显生成痕迹、结构崩坏、边缘融合失败 |

红线输出不只是布尔值：每条 violation 需记录**类型 + 位置 + 证据描述**。

### Layer 1 - 方向判断

- 系统（F.1/F.2 的产出）必须**显式声明**本次选择发展的维度。这是对上游的接口要求，不只是裁判内部的事。
- 评分逻辑：
  - 声明维度命中 Target Card 的 `candidate_dimensions` 之一：评契合度（0-4）
  - 未命中：额外评"系统选的维度对这张照片是否也成立"（合理的未命中不必然是 0 分）
- 输出包含一句话理由；如适用，指出被忽略的更优维度。

### Layer 2 - 执行判断

每项 0-4 分，必须附证据：

| 项目 | 问题 |
|---|---|
| 实现度 | 声明维度上是否有可感知的、朝目标方向的变化？ |
| 火候 | 变化幅度是否足够（发展不足 = 白做）且不过度（过火 = 失去摄影感，滑向"效果图"）？ |
| 连带代价 | 是否为发展该维度牺牲了原图其他已成立的价值？ |

### Layer 3 - 总裁决（成对比较，不用绝对分）

**裁决只依赖 pairwise 结果 + 红线门。Layer 1/2 的分数仅作归因证据，绝不参与裁决。**理由：LLM 的绝对评分跨轮漂移严重，成对比较的稳定性与人机一致性明显更好。

- `candidate vs original`：better / same / worse
- `candidate_A vs candidate_B`（同轮内）：排序
- **双向协议（D6）**：每对比较交换位置各做一次；两个方向结果不一致时记 `same`。以 Call-2 成本翻倍为代价抵消 LLM 位置偏差。

## 4. 封闭维度词表（`dimension_vocab_v0`）

| Key | 名称 | 覆盖范围 |
|---|---|---|
| `light_shadow` | 光影氛围 | 光比、方向光、明暗层次 |
| `color_mood` | 色彩情绪 | 色调、色彩关系、饱和策略 |
| `subject_impact` | 主体表现力 | 主体突出、清晰度、质感 |
| `composition` | 构图裁切 | 裁剪、平衡、视觉引导 |
| `atmosphere` | 氛围叙事 | 天气感、时间感、情绪 |
| `moment` | 瞬间感 | 动态、表情、抓拍价值 |
| `other` | 逃生口 | 必须附文字说明 |

治理规则：

- 词表版本化；版本号写入每条实验签名。
- 若某个 loop 周期内 `other` 占比超过 **15%**，触发人工词表评审。

## 5. 两次调用的裁判流程

```
Candidate ──► Call-1  红线判定  (P.3_eval_redline)
                 │ fail ──► 出局；记 failure_tags；不做 Call-2
                 │ pass
                 ▼
              Call-2  方向 + 执行 + 裁决  (P.3_eval_quality)
```

- Call-1 失败者完全跳过 Call-2（省成本 + 关注点干净分离）。
- 两段提示词均由人工定义并固定（不自动演进），其 hash 写入实验签名。

## 6. F.4 二次验证的计分规则

> 依据 Golden Set 设计修订：计分**按类别区分**。若统一使用 `same = 0`，good case（克制本身就是成功）将永远无法贡献正分，会误导采样器。详见 `doc/MVP.0.1-phase1-goldenset-zh-cn.md`。

单次验证实验按 case 类别计分：

| 类别 | 成功判据 | 计分 |
|---|---|---|
| bad | better | better = +1 / same = 0 / worse = -1 / redline fail = -2 |
| good | same 或 better（克制） | same = +1 / better = +1 / worse = **-2**（回归罪加一等） |
| redline | redline pass | pass = +1 / fail = **-3**（底线，惩罚最重） |

晋级条件（Case Recipe -> Pattern Patch），明确初值：

- 在 **>= k = 3** 个不同子类样本上完成验证
- **总分 > 0** 且 **worse 率 < 25%** 且 **redline fail = 0**
- k 与阈值后续可调，以上为明确初值。

## 7. 输出 JSON Schema

```json
{
  "case_id": "…",
  "candidate_id": "…",
  "judge_meta": {
    "judge_model": "model-name@version",
    "redline_prompt_hash": "…",
    "quality_prompt_hash": "…",
    "dimension_vocab": "dimension_vocab_v0"
  },
  "redline": {
    "pass": true,
    "violations": [
      {"type": "identity", "location": "面部区域", "evidence": "…"}
    ]
  },
  "direction": {
    "declared_dimension": "light_shadow",
    "hit_target_card": true,
    "score": 3,
    "rationale": "…",
    "missed_better_dimension": null
  },
  "execution": {
    "realization": {"score": 3, "evidence": "…"},
    "intensity": {"score": 2, "evidence": "过火：天空饱和度超出自然范围"},
    "collateral_damage": {"score": 4, "evidence": "…"}
  },
  "verdict_vs_original": "better",
  "pairwise": [
    {"against": "candidate_B", "result": "better", "bidirectional_agreed": true}
  ],
  "failure_tags": ["over_saturation"],
  "confidence": "high"
}
```

## 8. 裁判自身可靠性治理（从第一天就做）

1. **锚定样例**：准备 5-10 组人工标定的 (original, candidate, 期望裁决) 三元组，作为 rubric 中的 few-shot 锚点，压制 LLM 裁判"偏爱高饱和高对比"的已知偏差。
2. **版本钉死**：裁判模型版本 + 两段 P.3_eval 提示词 hash 写入每条实验签名。裁判换版本 = 历史分数不可比。
3. **人工抽检**：每个 loop 抽取固定比例裁决做人工复核，跟踪人机一致率；低于阈值时人工校准 rubric——**绝不**让 P.3_eval 自动演进。

## 9. 遗留事项（延后处理，持续跟踪）

- 人机一致率的具体阈值（建议先取 80%，有数据后调整）
- 锚定样例集的构建（依赖 Golden Set / Target Card 设计，即下一份设计文档）
- ~~存在专业精修参考图时，是否将其作为改善方向提示提供给 Call-2~~ **已定案：v0 不适用**——Golden Set v0 无精修参考图（纯文本标注）。引入参考图后再议。
