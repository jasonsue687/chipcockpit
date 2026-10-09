---
name: Read EDA Concept
description: This skill should be used when the user asks to "explain [EDA concept]", "what is [term] in chip design", "read EDA concept [topic]", "what does [term] mean in physical design", "explain CTS", "explain placement optimization", "what is IR drop", "explain timing closure", or needs a conceptual explanation of a physical design or EDA term rather than a specific command lookup. Returns concept explanations from the expert knowledge base.
version: 0.1.0
---

# Read EDA Concept

Retrieve and explain a conceptual topic in chip physical design (PD) or EDA. Unlike `search-eda-command` which looks up specific Tcl commands, this skill handles conceptual and educational queries: "What is X?", "Explain Y", "How does Z work?".

## When to Use This Skill

Use this skill for:
- Conceptual definitions: "What is hold slack?", "What is ECO?"
- Process explanations: "How does CTS work?", "What happens during route_opt?"
- Troubleshooting guidance: "Why is my design congested?", "What causes setup violations?"
- Stage overviews: "Walk me through the Innovus flow"

Use `search-eda-command` instead when the user needs syntax or arguments for a specific Tcl command.

## How to Execute

### Step 1: Identify the concept

Extract the key concept from the user's query. Normalize to lowercase:
- "CTS" → `cts` → Clock Tree Synthesis
- "IR drop" → `ir_drop`
- "timing closure" → `timing_closure`

### Step 2: Check expert base first

Use `list-expert-topics` logic to find a matching document in `knowledge/expert_base/`:
1. Scan for files whose title or tags match the concept keyword
2. If found, read and return that document via `read-expert-doc`

### Step 3: Synthesize from built-in knowledge

If no matching expert document exists, synthesize an explanation covering:
1. **Definition**: What is it in 1-2 sentences?
2. **Why it matters**: Impact on design quality, timing, power, area
3. **Key parameters**: What values/thresholds matter?
4. **Common issues**: What goes wrong and why?
5. **Related commands**: Link to 1-3 relevant Tcl commands (suggest using `search-eda-command`)
6. **Expert tip**: One actionable best practice

### Step 4: Cite sources

Always end with:
```
---
Source: Built-in PD knowledge | For command details, use 'search EDA command <tool> <command>'
```
Or if from expert base:
```
---
Source: knowledge/expert_base/<filename>.md
```

## Common PD Concepts Index

Use this index to route queries to the right resource:

| Concept | Category | Related Commands |
|---------|----------|-----------------|
| Floorplan | Physical | floorPlan, placeMacro, addHaloToBlock |
| Placement | Physical | place_opt, place_detail |
| CTS (Clock Tree Synthesis) | Timing | ccopt_design, report_clock_tree |
| Routing | Physical | route_opt, route_detail, route_eco |
| Timing Closure | Timing | optDesign, report_timing |
| IR Drop / Power Grid | Power | addStripe, addRing, analyzeIR |
| DRC / LVS | Signoff | verify_drc, verify_lvs |
| ECO (Engineering Change Order) | Utility | ecoRoute, ecoPlace |
| Hold Fix | Timing | optDesign -hold |
| Congestion | Physical | place_opt -congestion, report_congestion |

## Error Handling

- **Concept too vague**: Ask "Could you be more specific? For example, are you asking about [concept A] or [concept B]?"
- **Concept outside PD domain**: "This concept appears to be outside physical design scope. If you're asking about [related PD topic], I can explain that instead."

## Design Principle

This skill acts as the **conceptual layer** of the knowledge retrieval pipeline:

```
User query → [concept extraction] → expert_base lookup → synthesized answer
                                           ↓
                              search-eda-command for commands
```

Always prefer expert_base content over synthesized answers when available — expert docs contain team-specific context and validated workflows.
