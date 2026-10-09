#!/usr/bin/env python3
"""
pdf_to_structured.py — Offline EDA Markdown → Structured JSON Parser

Workflow:
  1. Use a vision model (e.g., GPT-4o, Claude) to convert EDA PDF → Markdown
  2. Place the resulting Markdown in knowledge/raw_pdfs/ (or any input path)
  3. Run this script to parse and extract Tcl command blocks
  4. Output JSON is saved to knowledge/processed_eda/<tool_name>.json

Usage:
  python parsers/pdf_to_structured.py \
      --input knowledge/raw_pdfs/innovus_user_guide.md \
      --tool innovus \
      --output knowledge/processed_eda/

  # Or process all .md files in a directory:
  python parsers/pdf_to_structured.py \
      --input-dir knowledge/raw_pdfs/ \
      --output knowledge/processed_eda/
"""

import re
import json
import argparse
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Section splitter: find Tcl command headings in Markdown
# ---------------------------------------------------------------------------

# Matches headings that look like Tcl command names.
# Rules to avoid matching generic section words like "Description", "Syntax", etc.:
#   1. Must contain at least one underscore OR start with a known verb prefix
#   2. OR be backtick-quoted (explicit command marker)
#   3. Must NOT be a common English word used as a section heading
#
# Examples matched:
#   ## place_opt
#   ### route_opt
#   ## `ccopt_design`
#   # set_db
#
# Examples NOT matched:
#   ## Description
#   ### Syntax
#   ## Arguments
#   # Overview

_SECTION_WORDS = frozenset([
    'description', 'syntax', 'usage', 'synopsis', 'arguments', 'argument',
    'options', 'option', 'parameters', 'parameter', 'flags', 'flag',
    'examples', 'example', 'overview', 'summary', 'introduction', 'notes',
    'note', 'see', 'related', 'returns', 'return', 'errors', 'error',
    'warnings', 'warning', 'deprecated', 'since', 'version', 'changelog',
    'references', 'reference', 'index', 'contents', 'table',
])

# Matches headings that are likely Tcl command names:
#   - Contains underscore (place_opt, route_opt)
#   - OR backtick-quoted (`ccopt_design`)
#   - Common Tcl command verb prefixes: set_, get_, report_, add_, create_, etc.
COMMAND_HEADING_RE = re.compile(
    r'^(#{1,4})\s+(`[a-z][a-z0-9_:]*`'           # backtick-quoted command
    r'|[a-z][a-z0-9]*_[a-z][a-z0-9_]*'           # snake_case with underscore
    r'|(?:set|get|report|add|create|delete|remove|init|run|place|route'
    r'|opt|check|verify|write|read|save|load|generate|analyze|fix'
    r'|update|clear|reset|open|close|exec|source|define|config'
    r'|ccopt|floorPlan|placeDesign|routeDesign)[A-Za-z0-9_]*'  # known prefixes
    r')(?:\s*[-–—(].*)?$',
    re.MULTILINE,
)

# Matches a Description section header
DESCRIPTION_RE = re.compile(
    r'^#+\s*(?:description|summary|overview)\s*$',
    re.MULTILINE | re.IGNORECASE,
)

# Matches a Syntax section header
SYNTAX_RE = re.compile(
    r'^#+\s*(?:syntax|usage|synopsis)\s*$',
    re.MULTILINE | re.IGNORECASE,
)

# Matches an Arguments / Options / Parameters section header
ARGUMENTS_RE = re.compile(
    r'^#+\s*(?:arguments?|options?|parameters?|flags?)\s*$',
    re.MULTILINE | re.IGNORECASE,
)

# Matches an Examples section header
EXAMPLES_RE = re.compile(
    r'^#+\s*(?:examples?|usage examples?|sample)\s*$',
    re.MULTILINE | re.IGNORECASE,
)

# Matches a table row for argument parsing:
# | -flag | type | description |
# | -flag | type | values | description |
TABLE_ROW_RE = re.compile(r'^\s*\|(.+)\|\s*$', re.MULTILINE)

# Fenced code block
CODE_BLOCK_RE = re.compile(r'```(?:tcl|shell|bash)?\s*\n(.*?)```', re.DOTALL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_markdown_formatting(text: str) -> str:
    """Remove bold, italic, inline code, and excessive whitespace."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_code_blocks(text: str) -> list[str]:
    """Extract all fenced code block contents."""
    blocks = CODE_BLOCK_RE.findall(text)
    result = []
    for block in blocks:
        lines = [line.rstrip() for line in block.strip().splitlines() if line.strip()]
        if lines:
            result.append('\n'.join(lines))
    return result


def parse_table_rows(text: str) -> list[dict]:
    """
    Parse a Markdown table into a list of argument dicts.
    Supports 3-col (name, type, description) and 4-col (name, type, values, description).
    Skips separator rows (--- rows).
    """
    rows = TABLE_ROW_RE.findall(text)
    arguments = []
    headers = None

    for row in rows:
        cells = [c.strip() for c in row.split('|')]
        cells = [c for c in cells if c]  # remove empty edge cells

        # Skip separator rows
        if all(re.match(r'^[-:]+$', c) for c in cells):
            continue

        # First non-separator row is header
        if headers is None:
            headers = [c.lower() for c in cells]
            continue

        # Parse argument row
        arg = {}
        for i, header in enumerate(headers):
            if i >= len(cells):
                break
            val = strip_markdown_formatting(cells[i])
            if not val or val in ('-', '—', 'N/A', 'n/a'):
                continue
            if 'name' in header or 'argument' in header or 'flag' in header or 'option' in header:
                arg['name'] = val
            elif 'type' in header:
                arg['type'] = val.lower()
            elif 'value' in header:
                # Split comma/pipe separated values
                arg['values'] = [v.strip() for v in re.split(r'[,|]', val) if v.strip()]
            elif 'default' in header:
                arg['default'] = val
            elif 'required' in header:
                arg['required'] = val.lower() in ('yes', 'true', 'required')
            elif 'description' in header or 'desc' in header:
                arg['description'] = val

        if arg.get('name'):
            # Infer type from name if not set
            if 'type' not in arg:
                if arg['name'].startswith('-'):
                    arg['type'] = 'flag'
                else:
                    arg['type'] = 'string'
            arguments.append(arg)

    return arguments


def infer_syntax_from_description(command: str, desc_text: str) -> Optional[str]:
    """
    Fallback: try to find a syntax-like line in description text.
    Looks for lines starting with the command name followed by flags.
    """
    for line in desc_text.splitlines():
        line = line.strip()
        if line.startswith(command) and ('-' in line or '[' in line):
            return line
    return None


# ---------------------------------------------------------------------------
# Command block parser
# ---------------------------------------------------------------------------

def parse_command_block(command: str, block_text: str) -> dict:
    """
    Parse a single Markdown block for one Tcl command.
    Returns a command dict matching the schema in references/eda-command-schema.md.
    """
    entry = {
        'command': command,
        'description': '',
        'syntax': '',
        'arguments': [],
        'examples': [],
        'see_also': [],
        'category': '',
    }

    # Split block into subsections by sub-headings
    subsections = re.split(r'^(#{1,5}\s+.+)$', block_text, flags=re.MULTILINE)

    current_section = 'preamble'
    section_text = {}

    i = 0
    while i < len(subsections):
        part = subsections[i]
        if re.match(r'^#{1,5}\s+', part):
            header = part.strip().lstrip('#').strip().lower()
            i += 1
            body = subsections[i] if i < len(subsections) else ''
            if re.match(r'description|summary|overview', header):
                current_section = 'description'
            elif re.match(r'syntax|usage|synopsis', header):
                current_section = 'syntax'
            elif re.match(r'arguments?|options?|parameters?|flags?', header):
                current_section = 'arguments'
            elif re.match(r'examples?|sample', header):
                current_section = 'examples'
            elif re.match(r'see also|related', header):
                current_section = 'see_also'
            else:
                current_section = 'other'
            section_text[current_section] = section_text.get(current_section, '') + '\n' + body
        else:
            section_text['preamble'] = section_text.get('preamble', '') + part
        i += 1

    # --- Extract description ---
    raw_desc = section_text.get('description', '') or section_text.get('preamble', '')
    # Strip code blocks from description
    clean_desc = CODE_BLOCK_RE.sub('', raw_desc)
    # Take first paragraph
    paragraphs = [p.strip() for p in clean_desc.split('\n\n') if p.strip()]
    if paragraphs:
        entry['description'] = strip_markdown_formatting(paragraphs[0])

    # --- Extract syntax ---
    syntax_text = section_text.get('syntax', '')
    code_blocks = extract_code_blocks(syntax_text)
    if code_blocks:
        # Take first code block line that contains the command name
        for block in code_blocks:
            for line in block.splitlines():
                if command in line:
                    entry['syntax'] = line.strip()
                    break
            if entry['syntax']:
                break
    if not entry['syntax']:
        # Look for inline code or plain text syntax line
        for line in syntax_text.splitlines():
            clean = strip_markdown_formatting(line)
            if clean.startswith(command):
                entry['syntax'] = clean
                break
    if not entry['syntax']:
        entry['syntax'] = infer_syntax_from_description(command, raw_desc) or command

    # --- Extract arguments ---
    args_text = section_text.get('arguments', '')
    if args_text:
        entry['arguments'] = parse_table_rows(args_text)
        # If no table found, try to parse flag lines like "-flag <value>   Description"
        if not entry['arguments']:
            entry['arguments'] = parse_flag_lines(args_text)

    # --- Extract examples ---
    examples_text = section_text.get('examples', '')
    if examples_text:
        code_blocks = extract_code_blocks(examples_text)
        for block in code_blocks:
            for line in block.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    entry['examples'].append(line)
        # Also look for inline code in non-code-block form
        if not entry['examples']:
            for line in examples_text.splitlines():
                m = re.search(r'`([^`]+)`', line)
                if m and command in m.group(1):
                    entry['examples'].append(m.group(1).strip())

    # --- Extract see_also ---
    see_text = section_text.get('see_also', '')
    for line in see_text.splitlines():
        clean = strip_markdown_formatting(line)
        # Look for command-like tokens (snake_case words)
        tokens = re.findall(r'\b([a-z][a-z0-9_]{2,})\b', clean)
        entry['see_also'].extend(tokens)

    # --- Infer category ---
    entry['category'] = infer_category(command, entry['description'])

    # Deduplicate and clean up
    entry['examples'] = list(dict.fromkeys(entry['examples']))[:10]
    entry['see_also'] = list(dict.fromkeys(entry['see_also']))[:10]

    return entry


def parse_flag_lines(text: str) -> list[dict]:
    """
    Fallback argument parser for non-table formats.
    Parses lines like:
      -effort <low|medium|high>   Controls optimization effort.
      -congestion                 Enables congestion-driven placement.
    """
    arguments = []
    FLAG_LINE_RE = re.compile(
        r'^(\s*)(-{1,2}[a-z][a-z0-9_-]*)(?:\s+<([^>]+)>)?\s{2,}(.+)$',
        re.IGNORECASE,
    )
    for line in text.splitlines():
        m = FLAG_LINE_RE.match(line)
        if not m:
            continue
        flag_name = m.group(2)
        value_hint = m.group(3) or ''
        description = strip_markdown_formatting(m.group(4))

        arg = {'name': flag_name, 'description': description}

        if not value_hint:
            arg['type'] = 'flag'
        elif '|' in value_hint:
            arg['type'] = 'enum'
            arg['values'] = [v.strip() for v in value_hint.split('|')]
        elif value_hint.lower() in ('string', 'str', 'name', 'file', 'filename', 'path'):
            arg['type'] = 'string'
        elif value_hint.lower() in ('int', 'integer', 'number', 'n'):
            arg['type'] = 'integer'
        elif value_hint.lower() in ('float', 'real', 'double'):
            arg['type'] = 'float'
        elif value_hint.lower() in ('list', 'args'):
            arg['type'] = 'list'
        else:
            arg['type'] = 'string'

        arguments.append(arg)
    return arguments


CATEGORY_KEYWORDS = {
    'floorplan': ['floorplan', 'floor_plan', 'die', 'core', 'io', 'pad', 'macro', 'halo'],
    'placement': ['place', 'placement', 'global_place', 'detail_place', 'legalize'],
    'cts': ['cts', 'clock_tree', 'ccopt', 'clock', 'cts_route'],
    'routing': ['route', 'routing', 'nanoroute', 'wire', 'via'],
    'timing': ['timing', 'setup', 'hold', 'slack', 'sta', 'opt_design', 'path'],
    'power': ['power', 'ir_drop', 'stripe', 'ring', 'vdd', 'vss', 'rail'],
    'signoff': ['drc', 'lvs', 'erc', 'verify', 'extract', 'parasitic'],
    'utility': ['report', 'set_db', 'get_db', 'source', 'write', 'read', 'save', 'load'],
}


def infer_category(command: str, description: str) -> str:
    """Infer a command's category from its name and description."""
    combined = (command + ' ' + description).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return category
    return 'utility'


# ---------------------------------------------------------------------------
# Main parser: split Markdown into command blocks
# ---------------------------------------------------------------------------

def parse_markdown_to_commands(markdown_text: str) -> list[dict]:
    """
    Split a Markdown document into per-command sections and parse each one.

    Strategy:
    1. Find all headings that look like Tcl commands (snake_case, lowercase)
    2. Treat the text between consecutive command headings as one block
    3. Parse each block into a structured command dict
    """
    # Find all command heading positions
    matches = list(COMMAND_HEADING_RE.finditer(markdown_text))

    if not matches:
        print("[WARN] No Tcl command headings found. Check Markdown format.", file=sys.stderr)
        return []

    commands = []
    seen = set()

    for idx, match in enumerate(matches):
        # group(1) = heading level (##), group(2) = command name
        raw_name = match.group(2).strip('`').strip()
        command_name = raw_name.lower()

        # Skip if the name is a known section word
        if command_name in _SECTION_WORDS:
            continue

        # Skip very short tokens (likely not commands)
        if len(command_name) < 3:
            continue

        # Determine block boundaries
        block_start = match.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown_text)
        block_text = markdown_text[block_start:block_end]

        # Skip duplicate commands (keep first occurrence)
        if command_name in seen:
            print(f"[WARN] Duplicate command '{command_name}' found, skipping.", file=sys.stderr)
            continue
        seen.add(command_name)

        # Skip blocks that are too short to be real command docs
        if len(block_text.strip()) < 30:
            continue

        try:
            entry = parse_command_block(command_name, block_text)
            # Only include entries with at least a description or syntax
            if entry['description'] or entry['syntax'] != command_name:
                commands.append(entry)
        except Exception as e:
            print(f"[ERROR] Failed to parse command '{command_name}': {e}", file=sys.stderr)
            continue

    return commands


def validate_commands(commands: list[dict]) -> list[str]:
    """Return a list of validation warnings."""
    warnings = []
    seen = set()
    for entry in commands:
        cmd = entry.get('command', '')
        if not cmd:
            warnings.append("Entry missing 'command' field")
            continue
        if ' ' in cmd:
            warnings.append(f"Command name contains space: '{cmd}'")
        if cmd in seen:
            warnings.append(f"Duplicate command: '{cmd}'")
        seen.add(cmd)
        if not entry.get('description'):
            warnings.append(f"Missing description for '{cmd}'")
        if not entry.get('syntax'):
            warnings.append(f"Missing syntax for '{cmd}'")
    return warnings


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def process_file(input_path: Path, tool_name: str, output_dir: Path) -> None:
    """Parse one Markdown file and write JSON output."""
    print(f"[INFO] Processing: {input_path}")

    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    markdown_text = input_path.read_text(encoding='utf-8')

    if not markdown_text.strip():
        print(f"[ERROR] Input file is empty: {input_path}", file=sys.stderr)
        sys.exit(1)

    commands = parse_markdown_to_commands(markdown_text)

    if not commands:
        print("[WARN] No commands extracted. Output JSON will be empty.", file=sys.stderr)

    # Validate
    warnings = validate_commands(commands)
    for w in warnings:
        print(f"[WARN] {w}", file=sys.stderr)

    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{tool_name}.json"
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(commands, f, indent=2, ensure_ascii=False)

    print(f"[INFO] Extracted {len(commands)} commands → {output_path}")
    if warnings:
        print(f"[INFO] {len(warnings)} warning(s) found. Review above.")


def main():
    parser = argparse.ArgumentParser(
        description='Convert EDA Markdown (from PDF via vision model) to structured JSON.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--input', '-i',
        type=Path,
        help='Path to a single Markdown input file.',
    )
    group.add_argument(
        '--input-dir',
        type=Path,
        help='Directory containing Markdown files to process. '
             'Each file will use its stem as the tool name unless --tool is set.',
    )
    parser.add_argument(
        '--tool', '-t',
        type=str,
        help='Tool name for output JSON filename (e.g., innovus, genus). '
             'Required when using --input. Optional with --input-dir (defaults to filename stem).',
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path('knowledge/processed_eda'),
        help='Output directory for JSON files. Default: knowledge/processed_eda/',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed extraction information.',
    )

    args = parser.parse_args()

    if args.input:
        if not args.tool:
            # Default tool name to file stem
            tool_name = args.input.stem.lower().replace('-', '_').replace(' ', '_')
            print(f"[INFO] --tool not specified, using '{tool_name}' from filename.")
        else:
            tool_name = args.tool.lower()
        process_file(args.input, tool_name, args.output)

    elif args.input_dir:
        if not args.input_dir.exists():
            print(f"[ERROR] Input directory not found: {args.input_dir}", file=sys.stderr)
            sys.exit(1)
        md_files = sorted(args.input_dir.glob('*.md'))
        if not md_files:
            print(f"[WARN] No .md files found in {args.input_dir}", file=sys.stderr)
            sys.exit(0)
        for md_file in md_files:
            tool_name = args.tool.lower() if args.tool else md_file.stem.lower()
            process_file(md_file, tool_name, args.output)


if __name__ == '__main__':
    main()
