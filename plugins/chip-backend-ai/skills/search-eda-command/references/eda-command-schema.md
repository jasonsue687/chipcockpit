# EDA Command JSON Schema Reference

Each file in `knowledge/processed_eda/` is named `<tool_name>.json` and contains a JSON array of command objects.

## Schema

```json
[
  {
    "command": "string (required)",
    "description": "string (required) — one-paragraph description of what the command does",
    "syntax": "string (required) — full Tcl syntax with optional/required markers",
    "arguments": [
      {
        "name": "string — flag or positional name, e.g. -effort or <filename>",
        "type": "string — one of: flag, string, integer, float, list, enum",
        "values": ["string — for enum types, list valid values"],
        "default": "string or null — default value if optional",
        "required": "boolean — true if argument is mandatory",
        "description": "string — what this argument controls"
      }
    ],
    "examples": [
      "string — full Tcl command invocation example"
    ],
    "see_also": ["string — related command names"],
    "category": "string — e.g. placement, routing, timing, floorplan, power"
  }
]
```

## Field Details

### `command` (required)
Exact Tcl command name as it appears in the tool. Case-sensitive. Use snake_case as Innovus/Genus commands are typically lowercase with underscores.

### `syntax` (required)
Full syntax string including:
- Required arguments in `<angle_brackets>`
- Optional arguments in `[square_brackets]`
- Mutually exclusive options in `{curly|braces}`
- Repeatable elements with `...`

Example:
```
route_opt [-effort <low|medium|high>] [-congestion] [-prefix <string>]
```

### `arguments` (optional, list)
Each argument object describes one flag or positional parameter.

**`type` values:**
- `flag` — boolean switch, no value (e.g., `-congestion`)
- `string` — takes a string value (e.g., `-prefix myDesign`)
- `integer` — takes an integer (e.g., `-threads 8`)
- `float` — takes a float (e.g., `-slack_threshold 0.1`)
- `list` — takes a Tcl list (e.g., `-cells {cell1 cell2}`)
- `enum` — restricted to specific values (use `values` field)

### `examples` (optional, list)
At least one complete, runnable Tcl example. Include realistic values, not placeholders.

### `see_also` (optional, list)
Names of related commands in the same tool. Used for navigation.

### `category` (optional)
Broad functional category. Recommended values:
- `floorplan` — die/core setup, macro placement
- `placement` — std cell placement
- `cts` — clock tree synthesis
- `routing` — signal routing
- `timing` — timing analysis and optimization
- `power` — power planning, IR drop
- `signoff` — DRC, LVS, extraction
- `io` — IO placement and assignment
- `utility` — general scripting utilities

## Example: Innovus place_opt Entry

```json
{
  "command": "place_opt",
  "description": "Performs global placement with integrated timing and congestion optimization. Combines placement, legalization, and optimization in a single step.",
  "syntax": "place_opt [-effort <low|medium|high>] [-congestion] [-timing_driven] [-prefix <string>]",
  "arguments": [
    {
      "name": "-effort",
      "type": "enum",
      "values": ["low", "medium", "high"],
      "default": "medium",
      "required": false,
      "description": "Controls the optimization effort level. Higher effort improves QoR but increases runtime."
    },
    {
      "name": "-congestion",
      "type": "flag",
      "required": false,
      "description": "Enables congestion-driven placement. Recommended for high-density designs."
    },
    {
      "name": "-timing_driven",
      "type": "flag",
      "required": false,
      "description": "Enables timing-driven placement for critical-path awareness."
    },
    {
      "name": "-prefix",
      "type": "string",
      "required": false,
      "description": "Prefix string for intermediate database saves."
    }
  ],
  "examples": [
    "place_opt -effort high -timing_driven",
    "place_opt -congestion -effort medium",
    "place_opt -effort low -prefix pre_place"
  ],
  "see_also": ["place_detail", "optDesign", "report_placement"],
  "category": "placement"
}
```

## Validation Rules

When generating JSON with `parsers/pdf_to_structured.py`, validate:
1. `command` field is non-empty and contains no spaces
2. `syntax` field is non-empty
3. `description` is at least 10 characters
4. No duplicate `command` values within the same file
5. `type` values are from the allowed set
6. `enum` type arguments must have a non-empty `values` list
