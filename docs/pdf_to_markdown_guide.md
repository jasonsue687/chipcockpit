# PDF → Markdown 知识库搭建指引

用 `pdf-to-markdown` 技能把一份 EDA PDF 变成可被 Claude 渐进式读取的分层知识库。


## 步骤

### 1. 进入 Claude Code

```bash
cd /path/to/chipcockpit
claude
```

### 2. 一句话触发技能

在会话里对 Claude 说：

> "把 `~/Downloads/NewTool_UG.pdf` 转成知识库"

Claude 会调用 `pdf-to-markdown` 技能，内部跑：

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/pdf_to_kb.py \
    ~/Downloads/NewTool_UG.pdf --doc-name NewTool_UG --overwrite
```

一键完成：字体分析 → PDF 转 Markdown → 分层构建 → 更新 `_global_index.md`。



### 3. 验证

让 Claude 做：

> "用 `read-eda-lab-doc` 打开 `NewTool_UG` 第一章，告诉我它讲什么。"

能一路从 `_summary.md` 下潜到 `detail_*.md` 即通过。

### 4. 发布部署

对 Claude 说：

> "升 plugin.json 版本号，commit & push，然后把插件更新到本地。"

Claude 会：改版本 → 语法检查 → `git commit && git push` → `/plugin update chip-backend-ai@chip-backend-ai`。

## 出了问题怎么办

结果不理想时，告诉 Claude 具体症状（"标题没识别出来"、"代码块没了"），它会按 `SKILL.md` 的 Step 1–6 自动切到分步流程：重跑字体分析 → 调 `STYLE_*` 参数 → 只重建分层。
