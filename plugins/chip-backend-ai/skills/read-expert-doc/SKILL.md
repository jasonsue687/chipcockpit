---
name: Read Expert Doc
description: This skill should be used when the user asks to "read expert doc", "load knowledge about [topic]", "show me the floorplan guide", "open expert document [filename]", "read [filename].md from expert base", "read Innovus doc", "show Innovus introduction", "读取专家文档", "打开专家文档", "读取 Innovus 文档", "查看 Innovus 专家文档", or wants to load the full content of a specific physical design expert document. This is the second-level progressive disclosure — only call after the user has identified the target file via list-expert-topics.
version: 0.1.0
---

# Read Expert Doc

Load and return the **full content** of a specific Markdown file from `knowledge/expert_base/`. This is the **second-level disclosure** — only execute after the user has selected a specific document from the index returned by `list-expert-topics`.

## When to Use This Skill

Use this skill when:
- The user explicitly names a file (e.g., "read example-floorplan-tips.md")
- The user selects a topic from the index returned by `list-expert-topics`
- A downstream task requires the full expert content

Do **not** use this skill speculatively or to pre-load multiple documents. Load one document at a time.

## Required Input

The user or calling context must provide a **filename** parameter, e.g.:
- `"example-floorplan-tips.md"`
- `"routing-congestion-guide.md"`

If no filename is provided, invoke `list-expert-topics` first and ask the user to select.

## How to Execute

### Step 1: Resolve the file path

Construct the full path:
```
$CLAUDE_PLUGIN_ROOT/knowledge/expert_base/<filename>
```

Validate:
- The filename must end with `.md`
- Do not allow path traversal (`../`, absolute paths)

### Step 2: Read the file

Use the Read tool with the full path. Read the entire file (no limit).

### Step 3: Return structured content

Return the content with a clear header indicating the source:

```
## Expert Document: <filename>

<full Markdown content>

---
Source: knowledge/expert_base/<filename>
```

### Step 4: Offer next actions

After returning content, suggest relevant follow-ups:
- "To search for an EDA command mentioned here, ask: 'Search EDA command [tool] [command_name]'"
- "To browse more topics, ask: 'List expert topics'"

## Error Handling

- **File not found**: Report `Document '<filename>' not found in knowledge/expert_base/. Run 'list expert topics' to see available files.`
- **Path traversal attempt**: Report `Invalid filename. Only filenames within knowledge/expert_base/ are allowed.`
- **Empty file**: Report `Document '<filename>' exists but is empty. Please add content.`
- **Non-.md extension**: Report `Only Markdown (.md) files are supported. Please specify a valid filename.`

## Design Principle

This skill implements **Level 2 Progressive Disclosure**:
- Loads full content only when the user has made a deliberate selection
- Prevents accidental context pollution from loading wrong documents
- Works in concert with `list-expert-topics` as a two-step retrieval pipeline

The two-skill pair (list → read) is the core expert knowledge access pattern for this plugin.
