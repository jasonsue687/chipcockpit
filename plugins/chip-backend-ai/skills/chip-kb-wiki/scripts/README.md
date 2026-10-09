# Bundled scripts

The skill ships with a working copy of the `tools/` package from `chip-knowledge-ai`. Use this when the user is in a fresh repo that doesn't have its own `tools/` registered.

## Layout

```
scripts/
└── tools/
    ├── parse_doc.py        # parse one source doc into parsed/<file>/*.md slices
    ├── scan_index.py       # rebuild INDEX.md from raw/ (preserves lazy fields by sha)
    ├── lint_wiki.py        # validate citation integrity in wiki/
    └── handlers/
        ├── common.py       # FileMeta, sha, paths, slugify
        ├── docx_handler.py
        ├── xlsx_handler.py
        └── pptx_handler.py
```

## Runtime requirements

- Python ≥ 3.11
- PyPI: `python-docx>=1.1.0`, `openpyxl>=3.1.0`, `python-pptx>=1.0.0`

Easiest install (uv):

```bash
uv pip install python-docx openpyxl python-pptx
```

Or via a host repo's `pyproject.toml` (`uv sync` will pick them up).

## Running

The scripts assume the cwd is the repo root (the one containing `raw/`, `parsed/`, `wiki/`). They write `parsed/` and `INDEX.md` relative to whichever ancestor of the cwd has `pyproject.toml` — that's what `find_repo_root()` in `handlers/common.py` does.

**Run from cwd as a module (preferred — the package imports `from tools.handlers import …`):**

```bash
# From the repo root:
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts python -m tools.parse_doc raw/<file>
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts python -m tools.scan_index
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts python -m tools.lint_wiki
```

**Or call the file paths directly** (uses the same package layout since `tools/__init__.py` exists):

```bash
cd <repo-root>
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts python ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/parse_doc.py raw/<file>
```

**If the host repo already registers these as scripts** (as `chip-knowledge-ai`'s `pyproject.toml` does), prefer those — they're the canonical entry points:

```bash
uv run parse-doc raw/<file>
uv run scan-index
# lint_wiki is not registered as a script there; use:
uv run python -m tools.lint_wiki
```

## How `find_repo_root` decides where things go

The scripts walk up from cwd looking for the first directory with a `pyproject.toml`. That ancestor is treated as the repo root; `raw/`, `parsed/`, `wiki/`, `INDEX.md` are all resolved relative to it.

This means:
- A host repo without a `pyproject.toml` won't work out of the box. Drop a stub `pyproject.toml` at the root if you need to bootstrap.
- Don't run the scripts from outside the repo tree — `find_repo_root` will fail loudly.

## Cache behavior recap

`parse_doc` keeps `parsed/<file>/_meta.json` with `{sha, source, last_parsed}`. On re-run, if the source's sha changed, it purges that directory's stale slices and re-parses. If unchanged and the target slice file exists, it's a no-op (cached). Use `--force` to bypass the cache.

## Keeping the bundled copy in sync

The canonical source is `chip-knowledge-ai/tools/`. To re-sync:

```bash
cp /path/to/chip-knowledge-ai/tools/{parse_doc,scan_index,lint_wiki,__init__}.py \
   ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/
cp /path/to/chip-knowledge-ai/tools/handlers/{__init__,common,docx_handler,xlsx_handler,pptx_handler}.py \
   ${CLAUDE_PLUGIN_ROOT}/skills/chip-kb-wiki/scripts/tools/handlers/
```

(No automated sync — manual `cp` keeps the picture honest.)
