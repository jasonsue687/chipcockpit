# Floorplan Best Practices

> Topic: Physical Design - Floorplan Stage
> Tags: floorplan, die-area, io-placement

## Overview

Floorplan quality has a direct impact on routing congestion and timing closure. This document captures key expert insights.

## Key Principles

1. **Macro placement first**: Place all hard macros before standard cell placement. Macros constrain routing channels.
2. **Keep power domains contiguous**: Avoid interleaving voltage domains to minimize level-shifter overhead.
3. **Halos and blockages**: Always add placement blockages around macros (typical: 5-10um) to avoid standard cells crowding macro edges.

## Common Mistakes

- Placing macros too close to chip edges without sufficient routing space for power straps.
- Forgetting to set `setPlaceMode -place_global_place_io_pins true` when IOs are timing-critical.

## Example Innovus Flow

```tcl
# Set die/core area
floorPlan -site core -s 500 500 10 10 10 10

# Place macros manually or with constraints
placeMacro -inst u_sram -loc {100 200} -orient R0

# Add halo
addHaloToBlock 10 10 10 10 u_sram
```
