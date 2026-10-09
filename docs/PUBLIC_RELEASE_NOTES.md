# Public release notes (ChipCockpit open tree)

This tree is a **cleaned, public-ready copy** of the private prototype.
It has a fresh git history (single initial commit). Nothing has been
pushed; the private repo is unchanged.

## Intentionally excluded

- Entire vendor-derived `knowledge/processed_eda/` corpora (user guides,
  lab manuals, and related PDF-converted trees)
- Raw vendor PDFs / `raw_pdfs/`
- Original DRAM / HBM physical-design skill with real product sizes
  (replaced by an EXAMPLE-only placeholder stub)
- Original RDL routing skill content with foundry paths, license hosts,
  and proprietary design names (replaced by generic simulated EXAMPLE stub)
- Long third-party EDA user-guide excerpts formerly under
  `knowledge/expert_base/innovus-ug-*.md`
- `.claude/settings.local.json` (machine paths and local allow-lists)
- `__pycache__`, `.pyc`, large binaries, `node_modules`

## Redactions applied

- Internal absolute home/workspace paths
- Teammate-style login IDs in onboarding docs → generic `dev-a` / `dev-b`
- Foundry / PDK path fragments and proprietary top-cell names
- Concrete license-server host examples

## Still OK

- Mentions of Cadence / Innovus as product names for interoperability
  (see top-level `NOTICE`)
- Generic lowercase “foundry” as a design concept (rule decks, shuttle)
- Mock / SIMULATED EDA flow under `core/sim/`

## Suggested GitHub names

- **Recommended:** `chipcockpit` (matches brand / site)
- Alternate: `chip-backend-ai` (keeps plugin / historical name)
