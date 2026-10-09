---
name: List Expert Topics
description: This skill should be used when the user asks to "list expert topics", "show available knowledge", "what expert docs are available", "browse expert base", "list chip design knowledge", "show me the expert knowledge index", "list Innovus docs", "what Innovus documents are available", "list expert documents", "show expert docs", "有哪些专家文档", "列出专家文档", "有哪些 Innovus 文档", "列出 Innovus 专家文档", or wants to discover what physical design expertise is available before reading details. This is the first-level progressive disclosure for the expert knowledge base.
version: 0.1.0
---

# List Expert Topics

Scan the `knowledge/expert_base/` directory and return a lightweight topic index. This is the **first-level disclosure** — return only titles and summaries, never full content. The goal is to let the LLM or user identify the right document before loading it into context.

## When to Use This Skill

Use this skill as the **entry point** whenever someone asks about chip physical design expertise without specifying a topic. Do not load individual Markdown files directly — return the index first and let the user select.

## How to Execute

### Step 1: Locate the knowledge base

The expert base is at:
```
$CLAUDE_PLUGIN_ROOT/knowledge/expert_base/
```

Use the Glob tool to find all `.md` files:
```
Pattern: $CLAUDE_PLUGIN_ROOT/knowledge/expert_base/**/*.md
```

### Step 2: Extract title and summary for each file

For each `.md` file found:
1. Read the first 10 lines using the Read tool (offset=1, limit=10)
2. Extract the **title**: the first line starting with `# ` (strip the `# ` prefix)
3. Extract the **summary**: the first non-empty, non-heading line, truncated to 80 characters
4. Record the relative file path from `knowledge/expert_base/`

### Step 3: Return a structured index

Return the result as a formatted Markdown table or JSON, never as full file contents. Use this format:

```json
{
  "expert_topics": [
    {
      "file": "example-floorplan-tips.md",
      "title": "Floorplan Best Practices",
      "summary": "Floorplan quality has a direct impact on routing congestion and timing closure...",
      "tags": ["floorplan", "die-area", "io-placement"]
    }
  ],
  "total": 1,
  "hint": "Use the 'read_expert_doc' skill with a filename to load full content."
}
```

### Step 4: Guide the next action

Always append a hint after the index:
> "To read the full content of any document, ask: 'Read expert doc [filename]'"

## Error Handling

- **Directory not found**: Report `knowledge/expert_base/ directory not found. Add Markdown files to populate the expert base.`
- **No .md files found**: Report `No expert documents found. Add Markdown files to knowledge/expert_base/.`
- **File read error**: Skip the file, log `[WARN] Could not read <filename>, skipping.`

## Design Principle

This skill implements **Level 1 Progressive Disclosure**:
- Returns metadata only (~100 tokens per document)
- Never loads full Markdown content
- Enables the LLM to make a targeted selection before using `read-expert-doc`

For the follow-up Level 2 disclosure, see the `read-expert-doc` skill.
