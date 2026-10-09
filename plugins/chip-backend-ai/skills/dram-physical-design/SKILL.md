---
name: dram-physical-design
description: >
  Placeholder skill for DRAM / HBM-style package physical-design scripting.
  This public ChipCockpit release ships NO real product sizes, bump pitches,
  TSV coordinates, or foundry LEF paths. Use only the clearly labeled EXAMPLE
  numbers below for simulation / teaching. Do not treat them as real silicon data.
version: 0.1.0-placeholder
---

# DRAM Physical Design — Placeholder (no real design data)

> **Public notice:** This is an honest stub. Real DRAM/HBM design parameters,
> bump arrays, TSV patterns, and foundry paths were removed from the open-source
> tree. Numbers below are **made-up EXAMPLE values** for mock flows only.

## EXAMPLE hierarchy (fake)

```
EXAMPLE_PKG_CAPACITY = 8 × EXAMPLE_BANK
EXAMPLE_BANK         = 4 × EXAMPLE_MACRO
EXAMPLE_MACRO        = 100.0 × 200.0 µm   # EXAMPLE only — not a real LEF size
```

## EXAMPLE tunable knobs (fake)

| Parameter | EXAMPLE value | Note |
|-----------|---------------|------|
| `bump_x_pitch` | 50.0 µm | EXAMPLE — not a product pitch |
| `bump_y_pitch` | 50.0 µm | EXAMPLE — not a product pitch |
| `chip_width` | 1000.0 µm | EXAMPLE die width |
| `chip_height` | 1000.0 µm | EXAMPLE die height |
| `tsv_keepout` | 5.0 µm | EXAMPLE keepout |

## What this skill should do (when you add real content privately)

1. Keep a single `design_params.tcl` as source of truth.
2. Generate place / net / bump / TSV / PG scripts from that file.
3. Run only against **your licensed** EDA install and **your** NDA'd PDK.

## Safety

- Never commit real foundry LEF/tech paths, license-server hosts, or product dimensions.
- Prefer the mock-EDA simulator under `core/sim/` for public demos.
