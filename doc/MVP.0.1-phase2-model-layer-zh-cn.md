# Keeper Factory MVP v0.1 - Phase 2：模型接入层

> 状态：已确认设计（第 3 阶段产物：开发/部署细节，第 2 项）  
> 上级文档：`doc/MVP.0.1-phase2-stack-zh-cn.md`

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| ML1 | 结构化输出 | 统一 **`generate_json()`** 封装：schema 约束由 pydantic 自动生成注入，返回后校验，**一次修复重试**，再失败记 `parse_failure` |
| ML2 | 节点可选字段 | `model_name` 外支持 `max_long_edge` / `thinking` / `reasoning_effort` / `max_tokens`；judge 节点默认 **`max_long_edge: 1024` + 开 thinking** |
| ML3 | 重试分层 | 接入层只处理**瞬时错误**（内部至多重试 2 次，指数退避）；pipeline 层（F.2 的单次重试）只处理**业务失败** |
| ML4 | token 统计 | **按 `model_name` x `{input, input_cached, output}` 分类**——各类计费标准不同；thinking token 计费归入 output，作为信息性子字段保留 |
| ML5 | dry-run 模式 | **v0 引入**：接入层加录制/回放开关；fixtures 存 `tests/fixtures/` |

## 2. 内置裁剪版 `llm_api.py`

来源：已验证的 `LLMAPI` / `VLLMAPI` / `ImageEditAPI` 三个类。裁剪规则：

- **保留**：类接口、按调用覆盖 `model_name`、瞬时错误判定（`is_transient_llm_error`）、重试/退避、token 用量提取、图片分辨率适配（`_image_edit_upload_dimensions` 等）
- **剥离**：`keeper.gemini_official` 导入及全部 Gemini 分支（v0 范围，依据 S4）
- **保持** `api_mode` 参数与分支结构，未来加回 Gemini 是 drop-in

## 3. ModelHub：按节点解析

进程级单例，读取 `config.json`，暴露以节点为键的调用：

```python
hub.generate_json(node="judge_redline", images=[...], user_prompt=..., schema=RedlineResult)
hub.image_edit(node="f2_image_edit", image=..., prompt=...)
```

职责：

1. 解析 `model_name` + 选项：`models.nodes[node]` -> 回落 `models.defaults`
2. 按（节点, model_name）采集每次调用的 token 用量
3. 把实际使用的模型写入实验记录 `env` 段（C5 已有要求）
4. 路由 dry-run 回放（ML5）

### 节点注册表（9 个）

| 节点 | API | 默认模型 | 默认选项 |
|---|---|---|---|
| `f1_candidate` | VLLM | gpt-5.5 | `max_long_edge: 768` |
| `f2_edit_prompt` | VLLM | gpt-5.5 | `max_long_edge: 768` |
| `f2_image_edit` | ImageEdit | gpt-image-2 | —— |
| `judge_redline` | VLLM | gpt-5.5 | `max_long_edge: 1024`，开 thinking |
| `judge_quality` | VLLM | gpt-5.5 | `max_long_edge: 1024`，开 thinking |
| `judge_pairwise` | VLLM | gpt-5.5 | `max_long_edge: 1024`，开 thinking |
| `f4_synthesis` | LLM | gpt-5.5 | 开 thinking |
| `f4_refine` | LLM | gpt-5.5 | 开 thinking |
| `f5_report` | LLM | gpt-5.5 | **关** thinking（纯文本整理，省钱） |

judge 用 `max_long_edge: 1024` 的理由：VLLM 默认 512 对"评伪影、评身份一致性"太低，会系统性漏判红线。

**注意事项**：三个 judge 节点换 `model_name` 属于**大版本事件**（judge-spec 的版本钉死规则）：历史分数不可比，锚定集需重建。用小模型降本应从低风险节点开始（`f5_report`、`f2_edit_prompt`）。

### config.json（`models` 段）

```json
{
  "models": {
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
  }
}
```

## 4. `generate_json()` 协议（ML1）

供全部 6 个 JSON 输出节点使用（F.1 候选、两个 judge、pairwise、F.4 两步）：

1. 在 prompt 末尾注入输出 schema 约束（由 pydantic 模型自动生成）
2. 返回后按对应模型解析 + 校验
3. 失败 -> **一次修复重试**：把原始输出 + 校验错误发回模型（"修复为合法 JSON"）
4. 再失败 -> 记 `parse_failure`（进 Ledger，等同 `execution_failure` 处理，不进裁判/不采纳）

## 5. 重试分层（ML3）

| 层 | 处理范围 | 策略 |
|---|---|---|
| 接入层 | 瞬时错误：网络、408/429/5xx（按 `is_transient_llm_error` 判定） | 内部至多重试 2 次，指数退避，对调用方透明 |
| Pipeline 层（F.2 单次重试） | 业务失败：编辑结果无图、JSON 修复失败、空输出 | 重试 1 次，再失败记 `execution_failure` / `parse_failure` |

两层各自的尝试次数都写入实验记录 `cost` 段。

## 6. token 统计（ML4）

分类遵循计费语义：**`model_name` x `{input, input_cached, output}`**。thinking token 计费在 output 内，作为信息性子字段保留。

实验记录 `cost` 段：

```json
"cost": {
  "calls": { "vlm": 5, "edit": 1 },
  "tokens": [
    { "model": "gpt-5.5",     "input": 12000, "input_cached": 8000, "output": 900, "output_thinking": 350 },
    { "model": "gpt-image-2", "input": 300,   "input_cached": 0,    "output": 0 }
  ]
}
```

`budget.jsonl` 每轮按（节点, model_name）聚合——直接支撑"按节点换小模型"的决策依据：跑几个批次后即可看到哪个节点 token 消耗最大、换模型能省多少。

## 7. Dry-Run / 回放模式（ML5）

- `kf run --dry-run`：接入层回放录制响应，零 API 消耗
- 首次真跑时录制，之后回放；fixtures 存 `tests/fixtures/`
- 核心价值：**开发期反复调试 F.1-F.5 编排**不烧真实调用；同时支撑确定性的 pipeline 测试

## 8. OSS 客户端

参照已验证的 `oss2ImageUpload` 模式（`oss2` SDK）：

- `upload_image`（路径 / PIL / numpy）/ `upload_json` / `upload_file` / `get_public_url`
- 构造参数取自 `config.json` 的 oss 段；凭证从环境变量解析（`access_key_env` / `secret_key_env`）
- 增加上传重试（3 次，退避）——OSS 抖动不能弄死一整轮 loop；最终失败则保留本地文件并标记 `upload_pending`，事后补传

## 9. 遗留事项（延后处理，持续跟踪）

- 价格表（用于换算货币成本；token 数现在就记，费率后补）
- judge 提示词中锚定图以 URL 引用还是每次重新上传（实现时定）
