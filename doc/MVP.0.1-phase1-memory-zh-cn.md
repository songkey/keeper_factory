# Keeper Factory MVP v0.1 - Phase 1：记忆（C2 Memory）设计

> 状态：已确认设计（第 2 阶段产物：组件详细设计）  
> 组件：C2 Memory  
> 上级文档：`doc/MVP.0.1-base-zh-cn.md`  
> 定位：Memory 是**知识库，不是日志库**。实验过程记录归 C5 Ledger；Memory 只存提炼后的判断知识。两者通过实验签名互相引用。

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| M1 | 晋级审批方式 | **批次制**：配置 n 轮为一批，批内自动晋级；批间通过邮件人工审批（事后追认制）。n=1 退化为每轮审批 |
| M2 | Case Recipe TTL | `config.json` -> `memory.case_recipe_ttl` 配置，**默认 5** 轮 |
| M3 | `image_class` 词表 | v0 用**自由文本**；先积累，后归纳词表 |
| M4 | Pattern Patch 冲突 | 提交人工决策，选项：**融合** 或 **保留其一** |
| M5 | 注入上限 | `config.json` -> `memory.max_injection_num`，**默认 3** |
| M6 | P.1 演进历史 | **不进 Memory**——归 C5 Ledger 管理 |

## 2. 存储形态：文件 + Git，不用数据库

MVP 规模（13 张图、单机、低并发）下：**一条知识 = 一个 YAML 文件**，整个 `memory/` 目录用 git 管理。

```
memory/
  case_recipes/          # 临时区（K.1）
    cr_0007.yaml
  pattern_patches/       # K.2
    pp_0003.yaml
  failure_notes/         # K.3
    fn_0005.yaml
  capability_notes/      # K.4
    cn_0002.yaml
```

理由：

- git diff 天然提供知识演进审计轨迹（谁在哪轮被晋级/降级，一目了然）
- 人工审计零工具成本；回滚 = git revert
- 允许人工随时修改，但必须走 git commit（留痕）
- 数据库留到 Golden Set 扩集之后

## 3. 通用信封字段（四类知识共有）

```yaml
id: pp_0003
type: pattern_patch            # case_recipe / pattern_patch / failure_note / capability_note
status: candidate              # candidate / pending_review / active / disputed / deprecated
created_loop: 12
updated_loop: 18
scope:                         # 适用边界，供检索匹配
  dimensions: [light_shadow]   # 封闭词表（dimension_vocab_v0）
  categories: [bad]            # bad / good / redline
  image_class: "逆光人像"       # v0 自由文本（M3）
confidence: medium             # low / medium / high（离散三档，不用连续数值）
evidence: [exp_sig_a1, exp_sig_b2, exp_sig_c3]     # 支持证据（实验签名）
counter_evidence: []                                # 反证（实验签名）
lineage:
  derived_from: cr_0007        # 晋级来源
```

两个刻意的简化：

- **confidence 用三档离散值**，不用连续数值和贝叶斯更新。规则：初始 `low`；每次独立验证通过升一档；出现任何反证降一档并同时转 `disputed`。小样本下的连续置信度是伪精度。
- 新增 **`disputed` 状态**（base 文档三态之外）：有未定论反证的知识。仍可注入 P.1 但必须带"存疑"标记；由 F.4 安排复验或人工裁定。

## 4. 状态机与批次化晋级（M1）

Loop 批次化：`config.json` -> `loop.batch_size = n`。

```
(F.4 达到晋级门槛) ──► candidate    [批内自动，立即生效可注入]
                          │  批次结束
                          ▼
                    pending_review  [仍可注入，带"待审"标记]
                          │  邮件审批
           ┌──────────────┼──────────────────┐
           ▼              ▼                   ▼
        active        deprecated          disputed（复验）
```

- **批内（第 1..n 轮）**：达到晋级门槛的知识自动晋级为 `candidate`，立即生效可被注入
- **批间（第 n 轮结束）**：loop 暂停，发送批次 Report 邮件，进入等待
- 人工邮件回复结构化文本完成追认：**approve / reject（转 deprecated）/ dispute（转复验）**
- 审批完成后下一批次才启动
- `n = 1` 退化为每轮人工审批
- 审批语义为**事后追认制**：批内自动晋级先生效，批末人工行使否决权

## 5. 邮件交互协议（v0 人机接口）

- **每轮结束**：发送 loop Report（信息性，不阻塞）
- **每批结束**：发送批次 Report + 待审清单（阻塞下一批）。回复采用结构化文本行，例如：

```
pp_0003: approve
pp_0005: reject
fn_0002: dispute
merge pp_0003 pp_0007
keep pp_0004 drop pp_0009
```

- **Pattern Patch 冲突（M4）**走同一通道：Report 列出冲突双方 + 两个选项（**融合** / **保留其一**），人工回复决策
- 后续 UI 后台仅替换通道载体，协议语义不变。这套审批动词表（approve / reject / dispute / merge / keep）就是未来 UI 的操作集。

## 6. 各类知识的专属载荷

### K.1 Case Recipe（临时区）

```yaml
case_id: case_003
declared_dimension: light_shadow
strategy_summary: "先声明保护项再给单一发展指令，edit prompt 用分步描述"
p1_variant_ref: exp_sig_a1          # 产生它的实验
judge_result_ref: exp_sig_a1        # 裁判输出存 Ledger，此处只留引用
validation_state: pending            # pending / validating / resolved
ttl_loops: 5                         # 来自 config memory.case_recipe_ttl
```

规则：Case Recipe **必须在 TTL 内被 F.4 处理**（晋级或抛弃），超时自动 discard。防止临时区变垃圾场。

### K.2 Pattern Patch

```yaml
principle: "逆光人像类：先冻结身份与天空结构，再单独发展主体光影，避免全局重曝"
prompt_fragment: |                   # 可直接注入 P.1 的可执行片段
  For backlit portraits: first declare frozen items (identity, sky structure),
  then issue a single light-development instruction for the subject only.
risk_note: "对天空占比 > 60% 的图可能触发天空伪影"
```

设计要点：**principle（原则）与 prompt_fragment（可执行片段）双轨**。原则供归纳与人读，片段供 F.1 直接消费。只存片段会退化成 prompt 收藏夹，违背总纲"Prompt 不是资产终点"。

### K.3 Failure Note

```yaml
failure_pattern: "同时给出 3 个以上发展指令时，edit model 倾向全图重绘"
trigger_conditions: "edit prompt 含多个并列增强动词"
failure_tags: [full_repaint, identity_drift]     # 与裁判 failure_tags 词表对齐
avoid_rule: "单轮 edit prompt 只保留一个主发展指令"
```

### K.4 Capability Note

```yaml
model: image_edit_model@v2.1        # 必须钉版本
behavior: "无法局部提亮而不影响相邻区域色温"
reproductions: [exp_sig_x1, exp_sig_x2]
workaround: "分两步：先全局曝光，再局部色温回拉"
```

规则：Capability Note **绑定模型版本**；模型升级后，该模型的全部 Note 自动转 `disputed` 待复验。

## 7. 读路径（Memory 如何被消费）

F.1 组装上下文的注入策略：

1. **Failure Note（active 状态）无条件全量注入**——下限保护不做检索过滤，v0 数量少撑得起
2. Pattern Patch / Capability Note 按 `scope` 匹配当前 case（维度 + 类别 + image_class 模糊匹配），按 `status（active > candidate）`、`confidence（高 > 低）`排序，上限 **`memory.max_injection_num`（默认 3）**
3. `disputed` 知识注入时附带存疑标记
4. 每轮实际注入的知识 id 全部写入实验签名——这是"这条知识到底有没有用"可归因的前提

## 8. 写路径：单一写入者

- 只有 **F.4** 有权写 Memory（晋级、降级、抛弃）
- F.3 只产生 Case Recipe 草稿放入临时区
- 人工可随时修改，但人工修改也走 git commit（留痕）

## 9. config.json（Memory 相关字段）

```json
{
  "loop": {
    "batch_size": 5
  },
  "memory": {
    "case_recipe_ttl": 5,
    "max_injection_num": 3
  }
}
```

## 10. 遗留事项（延后处理，持续跟踪）

- 邮件收发的实现方式（SMTP/IMAP 轮询 vs 邮件服务 webhook）——第 3 阶段（开发/部署）议题
- 审批回复的解析健壮性（笔误、部分回复、超时无回复的策略）——第 3 阶段
- `image_class` 词表归纳的触发时机（建议：每个批次边界回顾自由文本积累情况）
- 融合后的 Pattern Patch 是否保留双方 lineage（建议：保留，`lineage.merged_from: [pp_a, pp_b]`）
