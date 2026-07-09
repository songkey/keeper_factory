# Keeper Factory

MVP v0.1 — 图像编辑裁判的自进化实验系统。

Keeper Factory 围绕 Golden Set 运行多轮实验 loop：生成候选编辑方案 → 执行编辑 → 裁判打分 → 沉淀 Memory → 迭代 P.1 提示词。详细设计见 [`doc/`](doc/)。

## 仓库结构

```
keeper_factory/
  config.example.json   # 配置模板（复制为 config.json，不入 git）
  prompts/              # Jinja 提示词（含预打标 p0_*）
  src/keeper_factory/   # 主程序
  tools/                # 独立工具脚本
  data/                 # 独立 git 仓库，运行时数据（不入主仓库 git）
    goldenset/          # 测试集（case_*/original.jpg + target_card.yaml）
    goldenset/anchors/  # 裁判锚定集
    memory/             # 知识库 YAML
    ledger/             # 实验记录、checkpoint、报告
  doc/                  # 设计文档
```

## 安装与初始化

```bash
uv sync --extra dev
cp config.example.json config.json
# 编辑 config.json：模型、OSS、邮件等；*_env 字段填写环境变量名
export KF_LLM_API_KEY=... KF_OSS_AK=... KF_OSS_SK=... KF_MAIL_PASSWORD=...

# 新机器部署：搭目录 + 立刻探测 env / OSS / mail
uv run kf init

# 仅搭目录、不校验密钥（本地 scaffold / dry-run）
uv run kf init --skip-secrets
```

`kf init`（未加 `--skip-secrets`）会在脚手架完成后打印环境检查：

- 环境变量是否齐全（LLM / OSS / Mail）
- OSS DNS + 实际上传/回读探针
- Mail DNS + 实际发一封探测邮件

失败时 exit code 为 1，但 `data/` 脚手架仍会保留。可用：

```bash
uv run kf doctor                 # 只跑环境检查，不重建目录
uv run kf init --skip-mail-send  # 不发探测邮件
uv run kf init --skip-oss-write  # 不写 OSS 探针
uv run kf init --skip-checks     # 跳过全部探测
```

### 密钥配置

`config.json` 中以下字段的值是**环境变量名**（不是密钥本身），运行时会从 `os.environ` 读取：

| 配置路径 | 用途 |
|---|---|
| `models.api.api_key_env` | LLM / VLM API Key |
| `oss.access_key_env` / `oss.secret_key_env` | 阿里云 OSS |
| `mail.password_env` | 审批邮件 SMTP 密码 |

本地 scaffold / dry-run 可用 `--skip-secrets` 跳过校验；真实运行与预打标必须设置对应环境变量。

## CLI 命令

| 命令 | 说明 |
|---|---|
| `kf init` | 初始化 `data/`，并探测 env / OSS / mail |
| `kf doctor` | 仅跑环境探测（不重建目录） |
| `kf mail-test` / `kf oss-test` | 单独探测邮件 / OSS |
| `kf seed-demo` | 写入 1 个 demo case（`demo: true` 渐变占位图）+ anchor，仅供 dry-run；有真实 case 时不会进入 F.1/F.4a 采样 |
| `kf run [--loops N] [--dry-run] [--exp-name NAME]` | 执行进化 loop（可选用 `exp_name` 做 IO 隔离） |
| `kf resume [--force] [--exp-name NAME]` | 从 checkpoint 恢复（检测 config/prompt 漂移） |
| `kf status [--exp-name NAME]` | 查看当前 loop / batch / stage 状态 |
| `kf approve [--exp-name NAME]` | 本地审批兜底（按 `exp_name` 找批次文件与知识库） |
| `kf clear [--exp-name NAME]` | 清除本地 checkpoint/runtime 与临时产物（**不删除 OSS 记录**） |

产物与报告约定：

- F.2 / F.3 / F.4a 的 edit prompt、结果图、judge JSON **上传 OSS 后删除本地临时文件**；ledger 记录只保留 URL + sha256
- Golden Set 原图会上传供报告引用，**不删除**本地源文件
- F.5 报告含完整流程 / 候选输入 / 每实验图文对比（OSS URL）；邮件为 multipart（纯文本 + HTML，图片用 OSS URL 嵌入）

### `exp_name`（实验命名空间）

当你需要并行跑多套实验（互不影响 checkpoint / ledger / memory），可为命令添加 `--exp-name <NAME>`：

- **本地落盘隔离**：
  - 默认（不传）：`data/ledger/...` 与 `data/memory/...`
  - 传 `--exp-name expA`：
    - `data/ledger/exp/expA/...`
    - `data/memory/exp/expA/...`
- **OSS 路径隔离**：实验/报告对象的 key 会带 `expA/` 前缀段，避免覆盖默认空间的对象。

开发中若 `kf` 未反映最新代码，可用：

```bash
PYTHONPATH=src python -m keeper_factory.cli <command>
```

## Golden Set 准备

v0 目标：**13 case**（5 bad / 5 good / 3 redline）。每个 case 目录结构：

```
data/goldenset/case_002/
  original.jpg
  target_card.yaml
```

`case_id` **不必连续**：删除某个编号（如早期 demo `case_001`）不影响 F.1 / F.4a 采样；后续用 `preprocess_goldenset.py` 追加时会按现有最大编号 +1 分配（例如已有 `case_014` 则下一个是 `case_015`）。目录名须与 `target_card.yaml` 内的 `case_id` 一致。

Target Card 字段说明见 [`doc/MVP.0.1-phase1-goldenset-zh-cn.md`](doc/MVP.0.1-phase1-goldenset-zh-cn.md)。

### 1. 预处理 + 预打标（推荐）

将原始图片按类别目录整理好后，用 `tools/preprocess_goldenset.py` 批量导入：

```bash
python tools/preprocess_goldenset.py \
  --config config.json \
  --source bad:/path/to/bad \
  --source good:/path/to/good \
  --source redline:/path/to/redline
```

**预处理规则：**

- EXIF 旋转校正
- 长边超过 2048px 时等比缩小（`--max-edge` 可调）
- 统一保存为 `original.jpg`

**预打标：**

- 使用 `config.json` → `models.defaults.vlm` 指定的 VLM
- 依次生成 `scene_brief` 与 `target_card.yaml` 草稿
- 提示词模板（可先改再跑）：
  - `prompts/p0_prelabel_scene.jinja`
  - `prompts/p0_prelabel_target_card.jinja`

**增量导入：**

- 已处理图片的 SHA256 写入 `data/goldenset/_import_log.jsonl`
- 相同内容重复运行会自动跳过
- 新图片追加为 `case_NNN`（自动递增编号）

**常用选项：**

```bash
# 只预处理，不调用 VLM（占位 target_card）
python tools/preprocess_goldenset.py --skip-prelabel --source bad:/path/to/bad

# 每个 source 目录最多处理 2 张（调试）
python tools/preprocess_goldenset.py --limit 2 --source bad:/path/to/bad
```

### 2. 人工复核

预打标结果是草稿，导入后请逐条检查并修正 `target_card.yaml`：

- `candidate_dimensions` / `hint`（bad case 的 hint 必填）
- `must_keep` / `forbidden`
- 类别字段：`problem_note`（bad）/ `established_note`（good）/ `trap_note`（redline）

### 3. Anchor 集

首次真实 loop 前，在 `data/goldenset/anchors/anchor_v0.yaml` 准备裁判 few-shot 锚定样例（预热 loop 也会辅助构建，见设计文档）。

## Dry-Run 端到端（无需 API）

完整跑通一条 loop，不调用外部模型：

```bash
kf init --skip-secrets
kf seed-demo --skip-secrets
kf run --dry-run --loops 1
kf status
```

完成后可检查：

- `data/ledger/loops/loop_001.json`
- `data/ledger/reports/loop_001.md`
- `data/ledger/experiments/loop_001/`
- `data/ledger/checkpoint.json`（loop 正常结束时应被清除）

使用 `--exp-name expA` 时，对应路径为：

- `data/ledger/exp/expA/loops/loop_001.json`
- `data/ledger/exp/expA/reports/loop_001.md`
- `data/ledger/exp/expA/experiments/loop_001/`
- `data/ledger/exp/expA/checkpoint.json`

## 首次真实运行（Loop 0）清单

1. 准备 13-case goldenset，每个 case 有 `original.jpg` + 人工复核后的 `target_card.yaml`
2. 准备 `data/goldenset/anchors/anchor_v0.yaml`
3. 确认环境变量与 `config.json` 中的模型 / OSS 配置
4. 执行：

```bash
kf run --loops 1
```

中断后可 `kf resume`；若修改了 config 或 prompts 导致 hash 漂移，需 `--force` 或重新开 loop。

## 测试

```bash
uv run pytest
```

包含单元测试与 dry-run E2E（`tests/test_e2e_dry_run.py`）。

## 设计文档

| 主题 | 文档 |
|---|---|
| 总体架构 | [`doc/MVP.0.1-base-zh-cn.md`](doc/MVP.0.1-base-zh-cn.md) |
| Golden Set | [`doc/MVP.0.1-phase1-goldenset-zh-cn.md`](doc/MVP.0.1-phase1-goldenset-zh-cn.md) |
| 裁判规格 | [`doc/MVP.0.1-phase1-judge-spec-zh-cn.md`](doc/MVP.0.1-phase1-judge-spec-zh-cn.md) |
| Loop / Memory / Ledger | `doc/MVP.0.1-phase1-*-zh-cn.md` |
| 部署与 checkpoint | `doc/MVP.0.1-phase2-*-zh-cn.md` |
