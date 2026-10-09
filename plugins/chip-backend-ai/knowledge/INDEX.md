# EDA Knowledge Base Index

> Last updated: 2026-10-09 (public ChipCockpit release)
> This is the top-level index for EDA-related knowledge shipped with the plugin.

---

## Public policy

This open-source tree does **not** ship vendor user manuals, lab PDFs, or
`processed_eda/` corpora. Bring your own licensed documentation in a private
workspace if you need command lookup against real UGs.

## Expert Base (original tips only)

**Location**: `expert_base/`
**Browse with**: `list-expert-topics` skill

Currently includes original, non-vendor tips such as floorplan best practices.
Third-party EDA vendor manual excerpts are intentionally omitted.

## Simulated flow

Use `core/sim/mock_eda.py` and the flow templates under `templates/` for demos.
Product names like Innovus may appear as interoperability references only —
see the repository `NOTICE` file.

<!-- Add private tool entries only in private forks; do not commit PDKs or manuals. -->
