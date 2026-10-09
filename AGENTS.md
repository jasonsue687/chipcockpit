# Repository Guidelines

## 项目结构与模块组织

本仓库主要包含 `chip-backend-ai` 插件及其 EDA 知识库。插件主体位于 `plugins/chip-backend-ai/`：`core/router.py` 负责运行时路由，`parsers/` 存放离线解析工具，`skills/*/SKILL.md` 定义各类技能。知识库位于 `knowledge/`，其中 `expert_base/` 存放人工整理的专家 Markdown 文档，`processed_eda/` **不在本公开树中提供**（请在私有工作区自备已获授权的手册）。`knowledge/INDEX.md` 用于导航公开的 `expert_base/`。切勿提交 vendor PDF 或 `processed_eda/` 语料。

## 构建、测试与开发命令

当前没有包管理器清单或统一构建步骤，优先使用直接的 Python 命令：

**知识库相关：**
- `python3 plugins/chip-backend-ai/core/router.py list-topics`：列出专家文档主题。
- `python3 plugins/chip-backend-ai/core/router.py read-doc --file example-floorplan-tips.md`：验证专家文档读取流程。
- `python3 plugins/chip-backend-ai/parsers/pdf_to_structured.py --input <guide.md> --tool innovus --output /path/to/private/processed_eda`：从 Markdown 生成 EDA 命令 JSON。
- `python3 plugins/chip-backend-ai/skills/pdf-to-markdown/scripts/analyze_pdf_fonts.py example_ug.pdf --pages 30`：转换前分析 PDF 字体；需要 PyMuPDF。
- `python3 plugins/chip-backend-ai/skills/pdf-to-markdown/scripts/build_knowledge_base.py <source.md> --dry-run`：检查分层知识库生成结果。

**编排工作流相关（需要 PyYAML）：**
- `python3 plugins/chip-backend-ai/core/workflow/workspace.py init --path <dir> --name <project>`：初始化工作区。
- `python3 plugins/chip-backend-ai/core/workflow/workspace.py create-run --workspace <ws> --stage <stage>`：创建新 run 目录。
- `python3 plugins/chip-backend-ai/core/workflow/state_manager.py read --workspace <ws>`：读取状态机快照。
- `python3 plugins/chip-backend-ai/core/workflow/state_manager.py transition --workspace <ws> --event <event>`：执行状态转移。
- `python3 plugins/chip-backend-ai/core/workflow/decision_logger.py read --workspace <ws> --last-n 5`：读取最近决策日志。
- `python3 plugins/chip-backend-ai/core/workflow/spec_manager.py read --workspace <ws>`：读取当前 Spec。

**语法检查：**
- `python3 -m py_compile plugins/chip-backend-ai/core/router.py plugins/chip-backend-ai/parsers/pdf_to_structured.py`：检查 Python 语法错误。
- `python3 -m py_compile plugins/chip-backend-ai/core/workflow/workspace.py plugins/chip-backend-ai/core/workflow/state_manager.py`：检查工作流模块语法。

## 编码风格与命名规范

Python 使用 4 空格缩进，CLI 参数使用 `argparse`，路径处理优先使用 `pathlib.Path`，面向路由器的结果保持 JSON 输出。新增逻辑应拆成小函数，并提供明确错误信息。技能文档应保留 YAML front matter，写清触发条件，并提供可执行示例。人工维护的知识文档使用小写 kebab-case 文件名；生成的手册目录使用 `01_chapter_slug/` 这类编号前缀，叶子文件使用 `detail_*.md`。

## 测试指南

当前没有自动化测试套件。修改 Python 后，至少运行 `py_compile` 和一个相关 CLI 命令。修改知识库后，运行对应生成器的 `--dry-run`，并抽查受影响的 `_summary.md`、`detail_*.md` 和索引条目。修改技能文档时，确认路径和命令示例与实际插件布局一致。

## 提交与 Pull Request 规范

现有历史多为简短中文提交信息，并偶尔使用 Conventional Commit 前缀，例如 `feat: ...`、`docs: ...`。建议继续使用简洁、有范围的提交信息，如 `docs: update knowledge index` 或 `feat: add Innovus command parser`。PR 应说明修改的技能或知识范围，列出已运行的验证命令，关联相关 issue，并标注大规模生成内容或 PDF 派生变更，便于重点审查。

## 安全与配置提示

路径访问应限制在插件目录内；`router.py` 已对专家文档读取做路径穿越防护。除非仓库明确用于保存这些内容，不要提交专有手册或由其生成的大段摘录。
