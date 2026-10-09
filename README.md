# ChipCockpit (`chip-backend-ai`)

**Early open-source prototype** of an AI assistant for chip physical-design (backend) flows.

Website: [https://chipcockpit.org](https://chipcockpit.org) · Contact: [contact@chipcockpit.org](mailto:contact@chipcockpit.org)

License: [Apache-2.0](./LICENSE)

## What this is

ChipCockpit packages a Claude Code plugin (`plugins/chip-backend-ai`) plus a
read-only flow dashboard. The orchestration layer drives a **simulated**
Netlist→GDS-style recipe (spec → floorplan → place → CTS → route → signoff)
with human confirm gates. A mock-EDA layer emits loudly-`SIMULATED` reports so
you can exercise the cockpit **without** a licensed EDA install.

## What this is NOT

- Not a redistribution of third-party EDA vendor user manuals or labs.
- Not a foundry PDK, LEF/tech deck, or license-server config.
- Not production signoff software. Real correctness still comes from your
  licensed tools and your NDA'd process design kit.

Vendor product names (e.g. Innovus) appear only as interoperability references.
See [NOTICE](./NOTICE).

## Quick start

```bash
git clone https://github.com/<your-org>/chipcockpit.git
cd chipcockpit

# Optional: install as a local Claude Code marketplace
claude plugin marketplace add "$(pwd)" --scope local
claude plugin install chip-backend-ai@chip-backend-ai
```

Flow dashboard (read-only):

```bash
python3 scripts/flow_dashboard.py --workspace /path/to/project/.chipflow --open
```

See [docs/flow_dashboard_quickstart.md](docs/flow_dashboard_quickstart.md).

## Repository layout

| Path | Role |
|------|------|
| `plugins/chip-backend-ai/` | Claude Code plugin root |
| `plugins/chip-backend-ai/core/` | Router + flow state machine + mock EDA |
| `plugins/chip-backend-ai/skills/` | Decision / knowledge / utility skills |
| `plugins/chip-backend-ai/templates/` | Flow definition + Tcl templates |
| `plugins/chip-backend-ai/ui/` | Cockpit UI assets |
| `plugins/chip-backend-ai/knowledge/expert_base/` | Small **original** expert tips (no vendor UG dumps) |
| `scripts/flow_dashboard.py` | Read-only HTML dashboard |
| `docs/` | Design notes and onboarding (paths redacted for public) |
| `tests/` | Flow e2e harness + fixtures |

Skills `dram-physical-design` and `rdl-routing` ship as **placeholders** with
clearly labeled EXAMPLE numbers only.

## Knowledge base policy

This public tree **does not** include `knowledge/processed_eda/` or raw vendor
PDFs. If you have licensed manuals, keep them in a private workspace and point
the `pdf-to-markdown` skill at them locally — do not push them here.

## Trademark note

Cadence®, Innovus®, and other third-party names are trademarks of their
respective owners. ChipCockpit is independent and unaffiliated.

## Contact

- Email: contact@chipcockpit.org
- Site: https://chipcockpit.org
