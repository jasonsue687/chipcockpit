# ChipFlow 流程看板使用说明

本文档面向芯片设计流程的实际使用者，说明如何从一个全新目录或已有项目启动 Claude Code，并打开 ChipFlow 本地流程看板。

## 1. 使用前准备

确认已经安装 `chip-backend-ai` 插件：

```bash
claude plugin list
```

输出中应能看到已启用的 `chip-backend-ai`。如果刚安装或更新过插件，请先退出当前 Claude Code，再重新启动；看板日志与对话自动同步功能需要在新会话中加载。

如尚未安装，可在 `chip-backend-ai` 仓库根目录执行：

```bash
claude plugin marketplace add "$(pwd)" --scope local
claude plugin install chip-backend-ai@chip-backend-ai
```

如果已经安装但需要更新：

```bash
claude plugin marketplace update chip-backend-ai
claude plugin update chip-backend-ai@chip-backend-ai
```

更新后同样需要重新启动 Claude Code。

## 2. 全新项目：启动流程并打开看板

先创建并进入设计项目目录：

```bash
mkdir -p /path/to/my-chip-project
cd /path/to/my-chip-project
claude
```

在 Claude Code 中输入设计目标，例如：

```text
启动芯片后端流程。目标是跑通这个 block 的 route，重点检查 congestion 和 timing。
```

Claude Code 会在当前目录自动创建 `.chipflow/` 工作区，并开始生成需要确认的设计 Spec。看到“已初始化工作区”后，即可输入：

```text
打开当前项目流程看板
```

浏览器会自动打开看板。默认地址通常是：

```text
http://127.0.0.1:8765/
```

如果 `8765` 已被其他程序占用，插件会选择另一个本地端口。此时以 Claude Code 返回的实际 URL 为准。

## 3. 已有项目：继续流程并打开看板

项目目录中已经有 `.chipflow/` 时：

```bash
cd /path/to/existing-chip-project
claude
```

先输入：

```text
继续当前芯片后端流程
```

再输入：

```text
打开当前项目流程看板
```

也可以随时询问：

```text
流程页面链接是什么？
```

插件会返回当前看板的 workspace、URL 和运行状态。重复要求打开看板会复用已有服务，不会重复启动。

## 4. 如何查看节点、日志和大模型记录

进入页面后：

1. 顶部状态区显示当前生命周期、当前 Stage、当前节点和整体进度。
2. 中间流程图展示所有真实流程节点及其状态。
3. 点击任意节点，右侧详情区会显示该节点的输入、输出、运行产物、决策和人工确认信息。
4. “运行日志”区域显示该节点已经产生的 `.log`、`.out` 或 `.err` 文件。
5. “大模型交互记录”区域按时间显示归属于该节点的用户消息和 Claude 可见回复。

页面默认每 5 秒刷新一次。Claude Code 会在一轮回复结束、上下文压缩或会话退出时同步可见对话，因此刚发出消息时可能需要等待当前回复结束，再刷新或等待页面自动刷新。

看板只保存用户与助手可见文本及结构化审计摘要，不显示模型隐藏思考、系统提示、密码、凭据或普通工具原始返回。

## 5. 看板不会自动推进流程

看板是只读状态驾驶舱。点击节点只会查看历史信息，不会执行该节点，也不会改变状态。

要推进流程，请回到 Claude Code 输入自然语言，例如：

```text
继续
```

```text
继续当前芯片后端流程
```

```text
批准当前 Spec，继续执行
```

如果流程停在人工确认节点，必须在 Claude Code 中完成确认；随后看板会同步展示新的状态和交互记录。

## 6. 命令行手动启动和检查

通常建议在 Claude Code 中直接说“打开当前项目流程看板”。需要排查问题时，可以从 `chip-backend-ai` 仓库调用管理脚本。

在设计项目目录中启动后台服务：

```bash
python3 /path/to/chip-backend-ai/plugins/chip-backend-ai/skills/open-flow-dashboard/scripts/manage_dashboard.py \
  start --project-dir "$PWD"
```

查看状态和实际 URL：

```bash
python3 /path/to/chip-backend-ai/plugins/chip-backend-ai/skills/open-flow-dashboard/scripts/manage_dashboard.py \
  status --project-dir "$PWD"
```

关闭看板：

```bash
python3 /path/to/chip-backend-ai/plugins/chip-backend-ai/skills/open-flow-dashboard/scripts/manage_dashboard.py \
  stop --project-dir "$PWD"
```

也可以在 Claude Code 中直接输入：

```text
关闭流程看板
```

## 7. 常见问题

### 提示找不到 `.chipflow`

当前目录还没有启动过芯片流程。先在该目录启动 Claude Code，并输入“启动芯片后端流程……”。看到 `.chipflow/` 创建成功后，再打开看板。

### `http://127.0.0.1:8765/` 打不开

不要继续使用旧会话中保存的 URL。回到当前项目的 Claude Code 输入“流程页面链接是什么？”，打开它返回的最新 URL。端口可能不是 `8765`。

仍然打不开时，依次输入：

```text
关闭流程看板
打开当前项目流程看板
```

### 节点没有运行日志

先确认该节点是否真正执行过。尚未执行的节点没有日志属于正常情况；已执行节点的日志会从规范 `logs/` 目录以及实际 EDA run 的 `run_NNN/scripts/` 目录读取。

### 看不到刚产生的大模型交互记录

1. 等待当前 Claude Code 回复结束，并等待页面下一次刷新。
2. 确认插件已经更新，并在更新后重新启动过 Claude Code。
3. 确认 Claude Code 是从对应设计项目目录启动的，而不是从插件仓库或其他目录启动的。
4. 输入“流程页面链接是什么？”，确认页面连接的是当前项目的 `.chipflow`。

旧 Claude Code 会话产生的记录不会凭空出现在新工作区中；如需回填历史 transcript，可参考 [完整看板说明](flow_dashboard.md) 中的手动同步命令。

## 8. 最短操作路径

全新项目只需记住下面四步：

```bash
cd /path/to/my-chip-project
claude
```

然后依次输入：

```text
启动芯片后端流程。我的目标是：<填写设计目标>
```

```text
打开当前项目流程看板
```

最后打开 Claude Code 返回的 URL。之后在 Claude Code 中推进流程，在浏览器看板中查看状态、节点输入输出、运行日志和大模型交互记录。
