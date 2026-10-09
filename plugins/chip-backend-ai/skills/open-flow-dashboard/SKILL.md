---
name: open-flow-dashboard
description: 自动发现当前芯片设计项目中的 .chipflow 工作区，启动、打开、查询或停止本地只读流程驾驶舱。用户说“打开当前项目流程看板”“启动流程页面”“查看项目状态 GUI”“打开 ChipFlow Dashboard”“流程页面链接”“关闭流程看板”，或希望从当前 Claude Code 项目目录用自然语言查看 stage、节点、输入输出、运行日志、大模型交互摘要和结果时使用。
---

# 打开 ChipFlow 流程驾驶舱

使用捆绑的后台管理脚本。不要手写后台启动命令，不要在前台运行 HTTP 服务，也不要通过本技能推进流程。

## 启动或打开

在用户当前项目目录执行：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/open-flow-dashboard/scripts/manage_dashboard.py" start --project-dir "$PWD"
```

脚本会自动选择 `./.chipflow`；若不存在，则选择最近修改的 `.chipflow_*`。已有服务时复用原 URL，不重复启动。

解析脚本输出的 JSON。`status` 为 `started` 或 `already_running` 时，告诉用户已打开的 workspace 和 `url`；若系统未能自动打开浏览器，仍把 URL 返回给用户。

未发现工作区时，不要偷偷初始化或启动芯片流程。说明当前目录没有 `.chipflow`，提示用户先初始化/运行流程，或提供现有 workspace 路径。

## 查询状态或链接

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/open-flow-dashboard/scripts/manage_dashboard.py" status --project-dir "$PWD"
```

只汇报脚本返回的事实：运行状态、workspace、URL 和 PID。不要根据进程名猜测。

## 停止页面服务

用户明确要求关闭/停止时执行：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/open-flow-dashboard/scripts/manage_dashboard.py" stop --project-dir "$PWD"
```

## 约束

- 驾驶舱和 API 保持只读；不得借启动请求执行 `run-chip-flow`、mark、resolve-human、retry 或 rollback。
- 不把服务暴露到外网；管理脚本固定监听 `127.0.0.1`。
- 不修改用户的 `machine.yaml`、`flow_progress.yaml` 或产物。
- 用户提供明确 workspace 时，加 `--workspace <path>`，不要再自动发现。
