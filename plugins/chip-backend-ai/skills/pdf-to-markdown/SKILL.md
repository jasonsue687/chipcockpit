---
name: PDF to Markdown Converter
description: >
  Use this skill whenever the user wants to convert a PDF to Markdown, process an EDA PDF document,
  add support for a new PDF format, fix incorrect PDF conversion output, analyze PDF font structure,
  or adapt the pdf_to_markdown.py script for a new chip design document. Trigger on phrases like:
  "convert this PDF to markdown", "转换PDF到markdown", "帮我处理这个EDA PDF", "分析PDF的字体格式",
  "add support for new PDF format", "适配新的PDF格式", "这个PDF转换不正确", "PDF格式不对",
  "新的PDF文档怎么处理", "这个PDF的标题没被识别", "convert EDA user guide to markdown".
  Always invoke this skill before attempting PDF conversion — it prevents font guessing and
  provides a systematic workflow that works across all EDA PDF styles (lab guides, user guides,
  application notes, datasheets).
version: 0.2.0
---

# PDF to Markdown Converter

Convert chip design (EDA) PDF documents to structured Markdown, then build a hierarchical
knowledge base for progressive disclosure. The core script `pdf_to_markdown.py` handles
extraction; this skill guides you through adapting it for any new PDF format and building
the final folder structure.

**Two paths depending on the situation:**
- **One-shot conversion** → run `scripts/pdf_to_kb.py` once to analyze, convert, build, and validate
- **Known PDF** → run `pdf_to_markdown.py` directly (Style A or B already supported)
- **Unknown/new PDF** → run font analysis first, then adapt the configuration

For Claude Code or other agent runners, prefer the one-shot command first. It reduces repeated
permission prompts because analysis, PDF conversion, knowledge-base generation, and output checks
run inside one Python process.

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/pdf_to_kb.py \
    <input.pdf> \
    --doc-name <doc_name> \
    --version unknown \
    --overwrite
```

What it does:
1. Writes `font_analysis.json` next to the generated Markdown
2. Converts the PDF to `knowledge/processed_eda/<doc_name>/<version>/<doc_name>.md`
3. Builds the hierarchical knowledge base under `knowledge/processed_eda/<doc_name>/`
4. Updates `knowledge/processed_eda/_global_index.md`
5. Prints counts for `_summary.md`, `detail_*.md`, and extracted images

Use the step-by-step flow below only when the one-shot output has bad headings, missing code
blocks, leaking headers/footers, or otherwise needs PDF-style tuning.

---

## Step 0: Identify the Situation

Ask (or infer from context):
1. Which PDF file? (full path)
2. Has it been tried before with `pdf_to_markdown.py`? Did it produce correct output?
3. Is the output wrong (missing headings, garbled structure, code blocks not recognized)?

If the PDF is already handled well by the existing script → skip to **Step 4** (run directly).
If the PDF is new or producing incorrect output → follow **Steps 1–3** first.

---

## Step 1: Analyze Font Distribution

Run the bundled analysis script to profile the PDF's fonts before touching any conversion code:

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/analyze_pdf_fonts.py \
    <input.pdf> --pages 30
```

This outputs JSON with:
- **`fonts`**: every font name found, its size range, whether it's bold/mono, how often it appears
- **`large_sizes_observed`**: all distinct font sizes ≥ 11pt, sorted descending
- **`suggested_config`**: auto-inferred heading fonts, code fonts, and H1/H2/H3/H4 size thresholds
- **`sample_spans`**: 30 representative text spans with their font+size+content

**What to look for in the output:**

| Signal | What it means |
|--------|--------------|
| Font names with "Nimbus", "NimbusSan", "NimbusMon" | Style B (User Guide) — already supported |
| Font names with "Arial", "Times", "Calibri" | Style A (Lab/RAK) — already supported |
| Font names with "Helvetica", "Helvetica-Bold" | New style — needs config |
| Very large sizes (≥20) appearing rarely | Likely chapter/section titles (H1) |
| Medium sizes (14–18) bold | Likely subsection headings (H2/H3) |
| Monospace font family (Courier, Consolas, etc.) | Code blocks |
| One dominant size (10–12) non-bold | Body text |

---

## Step 2: Decide — Existing Style or New Style?

**Check if the PDF already matches Style A or B** in `pdf_to_markdown.py`:

```
Style A: heading_fonts includes "Arial" or "Calibri", code_fonts includes "CourierNewPSMT"
Style B: heading_fonts includes "NimbusSanL-Bold", code_fonts includes "NimbusMonL"
```

If the suggested config fonts **substantially overlap** with Style A or B:
→ Try running the script with `--start 1` and check output quality. Skip to **Step 4**.

If fonts are entirely different (e.g., Helvetica-based, DejaVu, custom embedded fonts):
→ Continue to **Step 3** to add a new style configuration.

---

## Step 3: Add a New Style Configuration

Open `pdf_to_markdown.py` (at `$CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/pdf_to_markdown.py`) and:

### 3a. Define a new style constant

Copy the structure of `STYLE_B` and fill in values from the analysis output:

```python
STYLE_C = {
    "code_fonts":    {"Courier", "CourierNew", "HelveticaMono"},   # from analysis: is_mono=true fonts
    "heading_fonts": {"Helvetica-Bold", "Arial-BoldMT"},           # from analysis: is_bold=true, large size
    "body_fonts":    {"Helvetica", "Arial"},                       # from analysis: dominant non-bold
    "h1_size":       22,    # from suggested_config.h1_size
    "h2_size":       18,    # from suggested_config.h2_size
    "h3_size":       14,    # from suggested_config.h3_size
    "h4_size":       11,    # from suggested_config.h4_size
    "skip_pages":    set(),
    "header_y_max":  60,    # from suggested_config.header_y_max
    "footer_y_min":  740,   # from suggested_config.footer_y_min
    "footer_fonts":  set(), # fonts used for page numbers (check sample_spans near footer)
    "page_num_font": "",    # font name used for standalone page number lines
}
```

**Tip on size thresholds**: the analysis gives you `large_sizes_observed`. Look for natural gaps —
if you see sizes [22.5, 18.0, 14.4, 11.0, 10.0], good thresholds are 22, 18, 14, 11. If sizes
cluster tightly (e.g., [11.2, 11.0, 10.8]), all are likely body text.

### 3b. Update `detect_style()` to recognize the new style

```python
def detect_style(doc: fitz.Document) -> str:
    page = doc[min(5, doc.page_count - 1)]
    fonts = set()
    for b in page.get_text("dict")["blocks"]:
        if b["type"] == 0:
            for line in b["lines"]:
                for span in line["spans"]:
                    fonts.add(span["font"])
    if any("Nimbus" in f for f in fonts):
        return "B"
    if any("Helvetica" in f for f in fonts):   # <- add your new condition
        return "C"
    return "A"
```

### 3c. Wire the new style into `convert()`

```python
cfg = STYLE_A if style == "A" else (STYLE_B if style == "B" else STYLE_C)
```

Also update the print statement:
```python
print(f"Detected style: {style} ({'RAK/Lab' if style == 'A' else 'User Guide' if style == 'B' else 'Custom'})")
```

---

## Step 4: Run the Conversion

Before running, ask the user for the version number (e.g., `v19.1`, `v22.1`). Use `unknown` if not provided. The output `.md` file should be saved to:
```
$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<version>/<doc_name>.md
```

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/pdf_to_markdown.py \
    <input.pdf> \
    $CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<version>/<doc_name>.md \
    [--start N] [--end N]
```

**Options:**
- `--start N` — skip first N-1 pages (useful to skip cover/TOC/copyright)
- `--end N` — stop at page N (useful for long docs, process in chunks)

**Resume mode**: if the conversion was interrupted, rerun with `--start <last_page+1>` — output
is appended rather than overwritten.

---

## Step 5: Verify Output Quality

Check the generated `.md` file for:

| Issue | Likely cause | Fix |
|-------|-------------|-----|
| No headings (everything is body) | `heading_fonts` doesn't match | Re-check font names — copy exact strings from analysis JSON |
| Too many headings (body text promoted) | `h3_size` or `h4_size` too low | Raise the threshold by 1-2pt |
| Code blocks missing | `code_fonts` wrong | Add the actual monospace font name from analysis |
| Header/footer text leaking in | `header_y_max`/`footer_y_min` wrong | Adjust: run analysis with `--pages 5`, inspect `sample_spans` for footer text |
| Page numbers appearing in body | `page_num_font` not set | Find the font used for standalone number lines in `sample_spans` |
| Cover/TOC pages included | `skip_pages` not set | Add page numbers to `skip_pages` in the config |
| Large chapter number promoted to H1 | Non-bold large text detected as heading | Add guard: check `is_bold(span)` is True for your heading font |

---

## Step 6: Debug Mode

If output still looks wrong after Step 5 fixes, run a targeted span dump to see exactly what the
script sees on a problematic page:

```python
import fitz
doc = fitz.open("problem.pdf")
page = doc[N-1]  # page N (0-indexed)
for blk in page.get_text("dict", sort=True)["blocks"]:
    if blk["type"] == 0:
        for line in blk["lines"]:
            for span in line["spans"]:
                print(f"  font={span['font']!r:40s} size={span['size']:5.1f} "
                      f"flags={span['flags']} text={span['text'][:60]!r}")
```

This shows the raw data — compare it against what your config expects.

---

## Common EDA PDF Styles Reference

| Document Type | Typical Fonts | Notes |
|--------------|--------------|-------|
| Cadence Lab Guide (RAK) | Arial-BoldMT, TimesNewRomanPSMT | Style A, no native TOC |
| Cadence User Guide (Innovus/Genus) | NimbusSanL-Bold, NimbusMonL | Style B, has native TOC |
| Synopsys User Guide | Helvetica, Helvetica-Bold | Needs Style C |
| Mentor/Siemens docs | Arial, CourierNewPSMT | Often similar to Style A |
| Power-integrity / SI docs (vendor-specific fonts) | Calibri, CourierNew | Check size thresholds carefully |
| IEEE paper (two-column) | Times-Roman, Courier | Wide body margins — header_y_max may need tuning |

---

## Step 7: Build Hierarchical Knowledge Base

After the output `.md` file passes quality checks in Step 5, run the bundled script to build the
hierarchical knowledge base in one command:

```bash
python3 $CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/build_knowledge_base.py \
    $CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<doc_name>.md \
    [--overwrite]   # re-generate if files already exist
```

The source file can be at either location:
- **No version subfolder** (preferred): `.../processed_eda/<doc_name>/<doc_name>.md`
- **With version subfolder**: `.../processed_eda/<doc_name>/<version>/<doc_name>.md`

The script auto-detects the layout from the path.

**Options:**
- `--dry-run` — print what would be written without creating any files (useful to verify parsing)
- `--overwrite` — overwrite existing files; also removes stale chapter folders from previous runs
- `--doc-name NAME` — override the document name (inferred from path by default)

### TOC-driven depth: the key principle

The script parses the `## Table of Contents` section of the Markdown file to determine:
1. **How many folder levels to create** — mirrors TOC depth exactly (no hardcoded limit)
2. **Which headings are valid chapter/section boundaries** — only headings matching TOC entries
   at that depth level are accepted (prevents false chapters from code blocks or decorative text)

| Document | TOC depth | Folder levels | Example path |
|----------|-----------|---------------|--------------|
| example_lab_doc | 2 | 2 | `example_lab_doc/01_module_1/detail_lab_1_1.md` |
| example_ug | 4 | 4 | `example_ug/02_intro/01_product_info/02_packages/detail_related_information.md` |

### Target directory structure

The hierarchy depth mirrors the TOC. For a 4-level TOC (e.g., example_ug):

```
processed_eda/
├── _global_index.md                           # Updated with entry for this manual
└── <doc_name>/
    ├── _summary.md                            # Manual-level: chapter table + FAQ pointers
    └── 01_chapter_slug/                       # TOC L1 → chapter folder
        ├── _summary.md                        # Sub-Folders table (or Sub-Files if L2 is leaf)
        ├── 01_section_slug/                   # TOC L2 → section folder
        │   ├── _summary.md                    # Sub-Folders table (or Sub-Files if L3 is leaf)
        │   ├── 01_subsection_slug/            # TOC L3 → subsection folder
        │   │   ├── _summary.md                # Sub-Files table (L4 = leaf)
        │   │   └── detail_topic_name.md       # TOC L4 → detail file
        │   └── 02_other_subsection/
        │       └── ...
        └── 02_other_section/
            └── ...
```

For a 2-level TOC (e.g., example_lab):

```
processed_eda/<doc_name>/
├── _summary.md
└── 01_module_1_slug/
    ├── _summary.md                  # Sub-Files table
    ├── detail_lab_1_1.md
    └── detail_lab_1_2.md
```

**Navigation signal in `_summary.md`**: Every `_summary.md` ends with either:
- `## Sub-Folders` — more subfolder levels exist; descend into a subfolder next
- `## Sub-Files` — leaf level reached; read a `detail_*.md` file next

### What the script does automatically

| Step | Action |
|------|--------|
| Parse TOC | Calls `extract_toc_tree()`: returns `max_depth` and per-level heading allowlists |
| Find boundaries | `find_headings_in_range()`: strict TOC allowlist at every depth — rejects code-block headings |
| Build tree | `parse_structure_tree()`: recursive, depth unbounded, mirrors TOC exactly |
| Non-leaf nodes | Create `NN_slug/` subfolder + `_summary.md` with `## Sub-Folders` table |
| Leaf nodes | Create `detail_<slug>.md` files in parent folder |
| Leaf `_summary.md` | TL;DR + Key Topics + `## Sub-Files` table |
| Manual `_summary.md` | Chapter table + FAQ pointers (Purpose left as TODO placeholder) |
| `_global_index.md` | Appends or updates the doc entry |
| Stale cleanup | On `--overwrite`, removes old `NN_slug/` folders before regenerating |

### After running: fill in TODO placeholders

The script leaves two fields for Claude to complete (takes ~5 tool calls, not 100):

1. **`<doc_name>/_summary.md` → `## Purpose`** — 2–3 sentence description of the document.

2. **`_global_index.md` → `**Description**`** — same text as Purpose above.

### Verify output

```bash
# Check directory structure (first 50 files)
find $CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name> -name "*.md" | sort | head -50

# Confirm Sub-Folders vs Sub-Files signal at each level
grep "Sub-Folders\|Sub-Files" \
    $CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/01_*/  _summary.md

# Spot-check a leaf detail file
cat $CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/01_*/detail_*.md | head -30
```

---

## Key Files

- **Converter script**: `$CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/pdf_to_markdown.py`
- **Font analyzer**: `$CLAUDE_PLUGIN_ROOT/skills/pdf-to-markdown/scripts/analyze_pdf_fonts.py`
- **Existing flat outputs**: `$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/<version>/`
- **New hierarchy root**: `$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/<doc_name>/`
- **Global index**: `$CLAUDE_PLUGIN_ROOT/knowledge/processed_eda/_global_index.md`
