#!/usr/bin/env bash
# deploy_local.sh — Local deployment of the chip-backend-ai Claude Code plugin.
#
# What it does:
#   1. Validates repo layout (marketplace.json, plugin.json, required dirs).
#   2. Runs py_compile on core workflow modules.
#   3. Syncs plugins/chip-backend-ai/ → ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/
#   4. Registers the repo path in ~/.claude/plugins/known_marketplaces.json
#   5. Updates ~/.claude/plugins/installed_plugins.json with new version + git SHA.
#
# Usage:
#   scripts/deploy_local.sh               # deploy current version
#   scripts/deploy_local.sh --purge-old   # also remove older cached versions
#   scripts/deploy_local.sh --dry-run     # show what would happen, make no changes
#
set -euo pipefail

# ---------- Paths ----------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="${REPO_ROOT}/plugins/chip-backend-ai"
MARKETPLACE_JSON="${REPO_ROOT}/.claude-plugin/marketplace.json"
PLUGIN_JSON="${PLUGIN_DIR}/.claude-plugin/plugin.json"

CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"
PLUGINS_ROOT="${CLAUDE_HOME}/plugins"
CACHE_ROOT="${PLUGINS_ROOT}/cache"
INSTALLED_JSON="${PLUGINS_ROOT}/installed_plugins.json"
MARKETPLACES_JSON="${PLUGINS_ROOT}/known_marketplaces.json"

# ---------- Flags ----------
PURGE_OLD=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --purge-old) PURGE_OLD=1 ;;
    --dry-run)   DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m   %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m  %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" -eq 1 ]; then echo "DRY-RUN: $*"; else eval "$@"; fi; }

# ---------- 1. Validate layout ----------
log "Validating repo layout at ${REPO_ROOT}"
[ -f "$MARKETPLACE_JSON" ] || die "missing ${MARKETPLACE_JSON}"
[ -f "$PLUGIN_JSON" ]      || die "missing ${PLUGIN_JSON}"
for d in skills agents core templates; do
  [ -d "${PLUGIN_DIR}/${d}" ] || warn "plugin sub-dir missing: ${d}"
done

# Extract names/versions via python (no jq dependency).
read -r MARKET_NAME PLUGIN_NAME PLUGIN_VERSION < <(python3 - "$MARKETPLACE_JSON" "$PLUGIN_JSON" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
p = json.load(open(sys.argv[2]))
print(m["name"], p["name"], p["version"])
PY
)
[ -n "$MARKET_NAME" ]    || die "failed to read marketplace name"
[ -n "$PLUGIN_NAME" ]    || die "failed to read plugin name"
[ -n "$PLUGIN_VERSION" ] || die "failed to read plugin version"

# Cross-check: marketplace.json must list this plugin.
python3 - "$MARKETPLACE_JSON" "$PLUGIN_NAME" <<'PY' || die "plugin not declared in marketplace.json"
import json, sys
m = json.load(open(sys.argv[1]))
names = [p["name"] for p in m.get("plugins", [])]
sys.exit(0 if sys.argv[2] in names else 1)
PY

log "marketplace=${MARKET_NAME}  plugin=${PLUGIN_NAME}  version=${PLUGIN_VERSION}"

# ---------- 2. Syntax check ----------
log "Compiling Python modules"
PY_FILES=(
  "${PLUGIN_DIR}/core/router.py"
  "${PLUGIN_DIR}/core/workflow/workspace.py"
  "${PLUGIN_DIR}/core/workflow/state_manager.py"
  "${PLUGIN_DIR}/core/workflow/decision_logger.py"
  "${PLUGIN_DIR}/core/workflow/spec_manager.py"
)
for f in "${PY_FILES[@]}"; do
  if [ -f "$f" ]; then
    python3 -m py_compile "$f" || die "py_compile failed: $f"
  else
    warn "skip missing file: $f"
  fi
done

# ---------- 3. Sync plugin to cache ----------
DEST="${CACHE_ROOT}/${MARKET_NAME}/${PLUGIN_NAME}/${PLUGIN_VERSION}"
log "Deploying → ${DEST}"
run "mkdir -p \"${DEST}\""
RSYNC_EXCLUDES=(
  --exclude '.DS_Store'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.git/'
)
if [ "$DRY_RUN" -eq 1 ]; then
  rsync -a --delete -n "${RSYNC_EXCLUDES[@]}" "${PLUGIN_DIR}/" "${DEST}/" | head -40
else
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "${PLUGIN_DIR}/" "${DEST}/"
fi

# ---------- 4. Register marketplace ----------
log "Registering marketplace in ${MARKETPLACES_JSON}"
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "")"
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"

python3 - "$MARKETPLACES_JSON" "$MARKET_NAME" "$REPO_ROOT" "$NOW_ISO" "$DRY_RUN" <<'PY'
import json, os, sys, pathlib
path, name, repo, now, dry = sys.argv[1:6]
p = pathlib.Path(path)
data = {}
if p.exists():
    data = json.loads(p.read_text() or "{}")
data[name] = {
    "source": {"source": "directory", "path": repo},
    "installLocation": repo,
    "lastUpdated": now,
}
out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
if dry == "1":
    print("DRY-RUN would write:", path)
    print(out)
else:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out)
PY

# ---------- 5. Update installed_plugins.json ----------
log "Updating ${INSTALLED_JSON}"
python3 - "$INSTALLED_JSON" "$PLUGIN_NAME" "$MARKET_NAME" "$PLUGIN_VERSION" "$DEST" "$GIT_SHA" "$NOW_ISO" "$DRY_RUN" <<'PY'
import json, sys, pathlib
path, plugin, market, version, install_path, sha, now, dry = sys.argv[1:9]
key = f"{plugin}@{market}"
p = pathlib.Path(path)
data = {"version": 2, "plugins": {}}
if p.exists():
    data = json.loads(p.read_text() or "{}")
    data.setdefault("version", 2)
    data.setdefault("plugins", {})

entry = {
    "scope": "user",
    "installPath": install_path,
    "version": version,
    "installedAt": now,
    "lastUpdated": now,
}
if sha:
    entry["gitCommitSha"] = sha

existing = data["plugins"].get(key, [])
# Preserve original installedAt if plugin was already installed.
if existing and isinstance(existing, list):
    prior = existing[0]
    if "installedAt" in prior:
        entry["installedAt"] = prior["installedAt"]

data["plugins"][key] = [entry]
out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
if dry == "1":
    print("DRY-RUN would write:", path)
    print(out)
else:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(out)
PY

# ---------- 6. Optional: purge older cached versions ----------
if [ "$PURGE_OLD" -eq 1 ]; then
  PARENT="${CACHE_ROOT}/${MARKET_NAME}/${PLUGIN_NAME}"
  if [ -d "$PARENT" ]; then
    log "Purging old versions in ${PARENT}"
    for v in "$PARENT"/*; do
      [ -d "$v" ] || continue
      if [ "$(basename "$v")" != "$PLUGIN_VERSION" ]; then
        run "rm -rf \"$v\""
      fi
    done
  fi
fi

log "Done. Restart Claude Code (or run /plugin) to load version ${PLUGIN_VERSION}."
