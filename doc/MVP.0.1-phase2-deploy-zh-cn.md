# Keeper Factory MVP v0.1 - Phase 2：运行形态与部署

> 状态：已确认设计（第 3 阶段产物：开发/部署细节，第 6 项——最终项）  
> 上级文档：`doc/MVP.0.1-phase2-stack-zh-cn.md`

---

## 1. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| DP1 | 数据仓远端备份 | **需要**——远程地址配置在 `config.json`（`paths.data_remote`）；每个批次边界自动 `git push`；**为空则不 push** |
| DP2 | 崩溃通知邮件 | **需要**——未捕获异常退出前尽力发送 `[KF][CRASH]` 邮件 |

## 2. 运行形态：前台 CLI，不做守护进程

`kf run --loops 15` 前台运行（放 tmux / nohup）：

- 批次边界本来就阻塞等邮件审批，常驻服务没有额外收益
- 一次运行是有限轮数，跑完自然退出；崩溃用 `kf resume`（见 checkpoint 文档）
- v0 不做 launchd/systemd 服务——那是 UI 后台时代的事

典型操作流：`kf run --loops 15` -> 每 5 轮暂停发审批邮件 -> 手机回复 `all ok` -> 进程自动继续 -> 跑完退出。随时用 `kf status` 看进度（只读 checkpoint 与 budget，不干扰运行）。

## 3. 崩溃通知（DP2）

任何未捕获异常，进程退出前尽力发送：

```
主题：[KF][CRASH] loop 012 stage f2
正文：traceback 摘要 + "执行 `kf resume` 恢复"
```

由此邮件通道覆盖全部三类事件：**审批、报告、故障**。

## 4. 数据备份（DP1）

- 图片与裁判全文已在 OSS（天然异地）
- `data/` git 仓库在每个批次边界向私有远端 push：

```json
{
  "paths": {
    "data_root": "./data",
    "data_remote": "git@github.com:you/keeper-factory-data.git"   // 空字符串 = 不 push
  }
}
```

- push 失败不致命：记告警、写入批次报告、下个边界重试。知识资产是系统最值钱的产出，单机磁盘不能是唯一副本。

## 5. 运行环境

纯 Python + API 调用（无 GPU、无重型库），macOS 与 Linux 行为一致。v0 在本机 Mac 上跑；将来迁服务器零代码改动。

## 6. Runbook（首次启动）

1. `uv sync`
2. 填写 `config.json`；导出 3 个环境变量（`KF_LLM_API_KEY`、`KF_OSS_AK`/`KF_OSS_SK`、`KF_MAIL_PASSWORD`）
3. `kf init`（创建 `data/` 嵌套 git 仓库与脚手架；若配置了 `data_remote` 同时设置远端）
4. 把 13 个 case + `target_card.yaml` 放入 `data/goldenset/`
5. 跑 loop 0 预热（`kf run --loops 1 --warmup`）；用其产出人工标定锚定集
6. `kf run --loops N`——正式循环开始

## 7. 遗留事项（延后处理，持续跟踪）

- 服务器迁移清单（环境变量、tmux vs systemd）——MVP 后
- 可选的 `kf doctor` 命令（config/环境变量/连通性自检）——实现期顺手做
