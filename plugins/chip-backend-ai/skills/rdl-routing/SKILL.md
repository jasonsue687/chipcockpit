---
name: rdl-routing
description: >
  Placeholder skill for redistribution-layer (RDL) routing concepts in a
  simulated Innovus-like flow. This public release contains NO foundry names,
  NO real PDK/LEF paths, NO license-server hosts, and NO proprietary design
  netlists. Examples use clearly labeled fake layer/cell names.
version: 0.1.0-placeholder
---

# RDL Routing — Simulated Examples Only

> **Public notice:** Vendor foundry paths, design names, license servers, and
> process-specific RDL rules were removed. Everything below is a **generic
> simulated EXAMPLE** for teaching obstacle-aware special-net routing ideas.

## EXAMPLE assumptions (fake process)

| Item | EXAMPLE value |
|------|---------------|
| RDL layer name | `EXAMPLE_RDL` |
| Wire width | 10.0 µm |
| Min spacing | 3.0 µm |
| Pitch | 13.0 µm |
| Example bump cell | `EXAMPLE_BUMP_A` (pad half = 15.0 µm) |
| Example IO cell | `EXAMPLE_IO_PAD` (pad half = 25.0 µm) |
| Top cell | `example_top` |
| DBU | 1000 |

## Workflow sketch (tool-agnostic)

1. Collect bump centers and IO shapes on `EXAMPLE_RDL`.
2. Build an obstacle map of existing shapes + blockages.
3. Route with L-/Z-shaped candidates; reject overlaps.
4. Emit special wires / shapes; run DRC on `EXAMPLE_RDL` only.
5. Iterate until SHORT/SPACING counts are zero in the **simulator**.

See `references/run-template.tcl` and `references/routing-procs.tcl` for
placeholder Tcl that uses only fake paths and EXAMPLE names.
