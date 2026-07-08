# Keeper Factory MVP v0.1 - Phase 2：技术栈与项目骨架

> 状态：已确认设计（第 3 阶段产物：开发/部署细节，第 1 项）  
> 上级文档：`doc/MVP.0.1-base-zh-cn.md`  
> 关联文档：`doc/MVP.0.1-phase2-model-layer-zh-cn.md`（第 2 项：模型接入层）

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| S1 | Python 与依赖管理 | **Python 3.12 + uv + pyproject.toml** |
| S2 | 对象存储 | **阿里云 OSS**（`oss2` SDK），客户端参照已验证的 `oss2ImageUpload` 模式实现 |
| S3 | 数据仓库 | **`data/` 为独立嵌套 git 仓库**——F.4 每轮的 memory 提交不能污染代码历史。代码仓 gitignore 掉 `data/`；`config.json` 用 `paths.data_root` 指向它 |
| S4 | 模型供应商（v0） | **gpt + gpt-image-2**，参照已验证的 `llm_api.py` 模式内置；Gemini 兼容延后（接口保持 drop-in 就绪） |
| S5 | 按节点配置模型 | 每个调模型的节点在 `config.json` 中有独立 `model_name`（及选项）；默认 **gpt-5.5 / gpt-image-2**（详见 model-layer 文档） |

## 2. 依赖清单

| 用途 | 包 | 理由 |
|---|---|---|
| 数据模型 | **pydantic v2** | 本系统是重 schema 系统（实验记录、知识条目、Target Card、裁判 JSON、config）；pydantic 是校验 + 序列化的单一事实源 |
| 模型 API | **openai** SDK（+ httpx） | OpenAI 兼容端点；适配逻辑收在接入层内部 |
| 模板 | **jinja2** | P.1 槽位模板与 Report 渲染 |
| YAML | **ruamel.yaml** | 知识文件读写保留注释与顺序（git diff 友好） |
| OSS | **oss2** | 阿里云 OSS SDK（S2） |
| 邮件 | 标准库 `smtplib` + `imaplib` | v0 不引第三方依赖；IMAP 轮询收审批回复 |
| git 操作 | subprocess 调 `git` | 比 GitPython 简单可控 |
| CLI | **typer** | 命令即函数 |
| 日志 | **loguru** | 零配置结构化日志 |
| 测试 | **pytest** | —— |

## 3. 项目骨架

```
keeper_factory/
  pyproject.toml
  config.json                  # 全量配置（第 3 阶段第 5 项收拢）
  doc/                         # 设计文档（本目录）
  prompts/                     # 人工维护的提示词资产，加载时计算 hash
    p1_initial.jinja           # P.1 初版模板（含槽位）
    p3_eval_redline.jinja
    p3_eval_quality.jinja
    p4_synthesis.jinja
    p4_refine.jinja
  data/                        # 运行数据根——独立嵌套 git 仓库（S3）
    goldenset/                 #   13 个 case + target_card.yaml
    memory/                    #   四类知识
    ledger/                    #   实验记录、签名、P.1 版本链、报告
  src/keeper_factory/
    config.py                  # pydantic 配置模型 + 环境变量解析
    schemas/                   # 全部数据 schema（experiment/knowledge/target_card/judge_result）
    models/                    # 模型接入层（见 model-layer 文档）
      llm_api.py               #   内置裁剪版 LLMAPI/VLLMAPI/ImageEditAPI
      hub.py                   #   ModelHub：按节点解析模型 + 用量采集
    goldenset/                 # Target Card 加载、轮换采样器
    memory/                    # 知识 CRUD、注入选择器、晋级状态机
    judge/                     # Call-1/Call-2 编排、双向 pairwise 协议
    loop/                      # F.1-F.5 编排、checkpoint
    ledger/                    # 记录写入、签名计算、DNR 索引、budget
    report/                    # Report 与短摘要渲染
    mail/                      # SMTP 发送、IMAP 轮询、审批回复解析器
    oss.py                     # 上传客户端（带重试）
    cli.py                     # 入口命令
  tests/                       # 命名为 tests（复数）
    fixtures/                  # dry-run/回放模式的录制响应
```

组织原则：**src 模块与 C1-C5 组件一一对应**（goldenset/memory/loop/judge/ledger），设计文档到代码零概念翻译。

## 4. CLI 命令集（初版）

| 命令 | 用途 |
|---|---|
| `kf init` | 初始化 `data/` 嵌套 git 仓库与目录脚手架 |
| `kf run --loops N` | 运行 N 轮（遵守批次边界） |
| `kf run --dry-run` | 回放模式：使用录制响应，不消耗 API（见 model-layer 文档） |
| `kf resume` | 从最近 checkpoint 恢复 |
| `kf status` | 当前 loop/批次/待审状态 |
| `kf approve` | 本地审批入口（邮件通道不可用时的兜底） |

## 5. 遗留事项（延后处理，持续跟踪）

- `config.json` 全量 schema 收拢——第 3 阶段第 5 项
- checkpoint 文件格式——第 3 阶段第 4 项
- 部署形态（launchd/cron vs 常驻进程）——第 3 阶段第 6 项
