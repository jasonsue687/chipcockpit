# ChipFlow 本地项目驾驶舱

ChipFlow Dashboard 是一个只读的本地页面，用来查看芯片后端流程当前状态、48 个真实节点、输入输出、运行日志与大模型交互摘要。页面不会执行节点、审批 Gate 或修改工作区状态。

如果你只想快速完成“进入设计项目 → 启动 Claude Code → 打开看板”，请先阅读 [流程看板快速上手](flow_dashboard_quickstart.md)。

## 启动

### 在 Claude Code 中自然语言启动

插件升级到 `0.4.6` 并重启 Claude Code 后，进入包含 `.chipflow/` 的设计项目目录：

```bash
cd /path/to/design-project
claude
```

然后输入：

```text
打开当前项目流程看板
```

插件会自动发现 workspace、选择可用的本地端口、在后台启动页面并打开浏览器。重复输入不会启动第二份服务，而是复用原来的 URL。

还支持：

```text
流程页面链接是什么？
关闭流程看板
```

若当前目录没有 `.chipflow` 或 `.chipflow_*`，技能只会报告缺少 workspace，不会自动初始化或推进流程。

### 命令行启动

在包含 `.chipflow/` 的设计项目目录中运行：

```bash
python3 /path/to/chip-backend-ai/scripts/flow_dashboard.py --open
```

也可以明确指定工作区：

```bash
python3 scripts/flow_dashboard.py \
  --workspace /path/to/project/.chipflow \
  --open
```

不加 `--open` 时，命令会输出本地 URL，默认是 `http://127.0.0.1:8765/`。按 `Ctrl+C` 停止服务。

## 页面展示的事实来源

页面在每次刷新时重新读取：

- `flow/flow_definition.yaml`：该项目启动时冻结的流程定义；不存在时仅用插件模板展示尚未启动的流程。
- `state/machine.yaml`：生命周期、各 stage、当前 run 和 retry budget。
- `state/flow_progress.yaml`：每个 step 的记录状态。
- `state/decisions.jsonl`：编排器最近的 dispatch、retry、rollback 等决策。
- `state/agent_interactions.jsonl`：按节点追加记录的用户请求、计划、决策依据、工具结果和人工确认摘要。
- `stages/`、`inputs/` 和 `run_NNN/`：输入、输出、报告、决策文件及 run 历史的实际存在情况。

节点详情会同时显示“记录状态”和磁盘事实。当节点记录为 `done` 但必需输出缺失，页面显示“不一致”；当输出已存在但进度仍是 `pending`，页面显示“产物已存在”。读取页面不会自动修改 `flow_progress.yaml`。

点击节点后，“运行日志”会识别 `stages/<stage>/logs/<step>.log`、`run_NNN/logs/<step>.*` 和实际 EDA 执行使用的 `run_NNN/scripts/<step>.*`。“大模型交互记录（摘要）”按时间展示节点对话。

插件通过 `Stop`、`PreCompact` 和 `SessionEnd` 钩子自动读取当前项目的 Claude Code transcript，并把用户可见消息、助手 `text` 消息同步到 `state/agent_interactions.jsonl`。同步器依据同一轮工具命令中的 `stage.step` 和工作区路径归属节点，并使用会话事件 ID 去重。旧项目可以手动回填：

```bash
python3 plugins/chip-backend-ai/core/workflow/session_sync.py sync \
  --workspace /path/to/project/.chipflow \
  --transcript /path/to/claude-session.jsonl
```

交互账本不是模型隐藏思考过程或 Claude Code 全局会话数据库的完整镜像。同步器明确忽略 `thinking`、`tool_result`、系统事件和隐藏提示，只保留用户与助手可见文本；结构化记录器另外保存可审计的事实摘要和文件引用。

## 只读与安全边界

- 服务默认只监听 `127.0.0.1`。
- 页面只有 GET 接口，没有推进、重试、审批或回滚接口。
- 文件查看限制在启动时选择的 workspace 内，拒绝绝对路径和 `..` 路径穿越。
- 页面每 5 秒自动刷新，也可以关闭自动刷新后手动读取。

## 本地验证

```bash
python3 -m py_compile \
  plugins/chip-backend-ai/core/workflow/interaction_logger.py \
  plugins/chip-backend-ai/core/workflow/session_sync.py \
  plugins/chip-backend-ai/core/workflow/dashboard.py \
  plugins/chip-backend-ai/core/workflow/dashboard_server.py \
  scripts/flow_dashboard.py

python3 -m unittest -v tests/test_flow_dashboard.py
```
