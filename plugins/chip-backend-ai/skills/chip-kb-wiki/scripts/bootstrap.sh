#!/usr/bin/env bash
# Bootstrap a fresh chip-kb-wiki workspace in the target directory.
#
# Usage:
#   scripts/bootstrap.sh                 # bootstraps cwd
#   scripts/bootstrap.sh /path/to/repo   # bootstraps the given dir (created if missing)
#
# Idempotent: re-running won't clobber existing wiki/index.md / wiki/log.md /
# pyproject.toml. Templates in wiki/_templates/ are always refreshed from the
# bundled copies so they stay in sync with the skill version.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$HERE/.." && pwd)"
TPL="$SKILL_ROOT/assets/templates"

TARGET="${1:-.}"
mkdir -p "$TARGET"
cd "$TARGET"
TARGET_ABS="$(pwd)"

echo "→ bootstrapping chip-kb-wiki at: $TARGET_ABS"

# 1. directory tree
mkdir -p raw parsed wiki/sources wiki/projects wiki/entities wiki/_templates
echo "  ✓ mkdir raw/ parsed/ wiki/{sources,projects,entities,_templates}/"

# 2. wiki templates (always refreshed)
cp "$TPL/source.md"  wiki/_templates/source.md
cp "$TPL/project.md" wiki/_templates/project.md
cp "$TPL/entity.md"  wiki/_templates/entity.md
echo "  ✓ refreshed wiki/_templates/{source,project,entity}.md"

# 3. starter index + log (preserve if user already has them)
if [ ! -f wiki/index.md ]; then
  cp "$TPL/index-starter.md" wiki/index.md
  echo "  ✓ seeded wiki/index.md"
else
  echo "  • wiki/index.md exists — keeping"
fi

if [ ! -f wiki/log.md ]; then
  cp "$TPL/log-starter.md" wiki/log.md
  echo "  ✓ seeded wiki/log.md"
else
  echo "  • wiki/log.md exists — keeping"
fi

# 4. stub pyproject.toml so find_repo_root() in scripts/tools/ can locate the repo root
if [ ! -f pyproject.toml ]; then
  cp "$TPL/pyproject-stub.toml" pyproject.toml
  echo "  ✓ wrote stub pyproject.toml (required: find_repo_root walks up looking for it)"
else
  echo "  • pyproject.toml exists — keeping (verify it lists python-docx / openpyxl / python-pptx)"
fi

# 5. .gitignore additions (parsed/ etc.)
if [ ! -f .gitignore ]; then
  cp "$TPL/gitignore-additions" .gitignore
  echo "  ✓ wrote .gitignore"
elif ! grep -q "^parsed/$" .gitignore 2>/dev/null; then
  echo "" >> .gitignore
  echo "# added by chip-kb-wiki bootstrap" >> .gitignore
  cat "$TPL/gitignore-additions" >> .gitignore
  echo "  ✓ appended chip-kb-wiki entries to .gitignore"
else
  echo "  • .gitignore already ignores parsed/ — keeping"
fi

cat <<EOF

Bootstrap complete at: $TARGET_ABS

Next steps:
  1. Install runtime deps (Python ≥ 3.11):
       uv pip install python-docx openpyxl python-pptx
     # or, if you used the stub pyproject.toml:
       uv sync

  2. Drop your first source doc(s) into raw/  (.docx / .xlsx / .pptx)

  3. Parse a doc into parsed/ slices:
       PYTHONPATH=$SKILL_ROOT/scripts python -m tools.parse_doc raw/<file>

  4. Follow the 7-step ingest in references/ingest-workflow.md to write
     wiki/sources/doc_001__<slug>.md (and any project/entity pages it touches).

  5. Lint:
       PYTHONPATH=$SKILL_ROOT/scripts python -m tools.lint_wiki
EOF
