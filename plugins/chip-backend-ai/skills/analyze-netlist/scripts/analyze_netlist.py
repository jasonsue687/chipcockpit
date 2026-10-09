#!/usr/bin/env python3
"""analyze_netlist.py — Verilog netlist structural analyzer.

Reads a gate-level or behavioral Verilog file and produces a Markdown report
covering: top port table, module hierarchy tree, combinational logic depth,
port fanin/fanout, and clock/reset tree fanout.

This is a lightweight regex-based parser. It is not a substitute for a real
Verilog frontend (yosys/pyverilog); it targets well-formed synthesized
netlists and best-effort lexical extraction for RTL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

CLK_PORT_RE = re.compile(r"^(clk|clock|.*_clk|.*_clock|.*clk_.*|.*clock_.*)$", re.IGNORECASE)
RST_PORT_RE = re.compile(
    r"^(rst|reset|rst_n|rstn|reset_n|resetn|por|por_n|por_b|"
    r".*_rst|.*_reset|.*_rstn|.*_rst_n|.*_resetn|.*_reset_n|.*_nreset|.*_resetb)$",
    re.IGNORECASE,
)
SEQ_CELL_RE = re.compile(
    r"(DFF|SDFF|FF[A-Z]?|LATCH|TLAT|FLOP|"
    # data-latch families used by TSMC/Synopsys/SAEDV style libs
    r"DLH[A-Z]?\d|DLL[A-Z]?\d|DLAT|DLT|SDLT|DLN|DLP|"
    # pulse generators / clock-domain cells often treated as sequential boundaries
    r"PG[A-Z]?\d|PULSE|CKLN|CKGT)",
    re.IGNORECASE,
)
SEQ_CK_PINS = {"CK", "CLK", "CP", "CLOCK"}
# Latch enable pins — checked only when the cell name matches a latch pattern.
LATCH_EN_PINS = {"E", "EN", "G", "GATE", "GN"}
SEQ_RST_PINS = {"R", "RN", "RB", "SET", "SETN", "CDN", "SDN", "RESET", "RESETN", "CLR", "CLRN"}
LATCH_CELL_RE = re.compile(r"^(LV_)?(DL[HL]?[A-Z]?\d|DLAT|DLT|LATCH)", re.IGNORECASE)

CONST_NETS = {"1'b0", "1'b1", "1'bx", "1'bz", "1'h0", "1'h1", "0", "1"}


@dataclass
class Port:
    name: str
    direction: str  # input / output / inout
    width: int = 1
    msb: int = 0
    lsb: int = 0


@dataclass
class Instance:
    inst_name: str
    cell_type: str
    connections: dict[str, str] = field(default_factory=dict)  # pin -> net


@dataclass
class Module:
    name: str
    ports: dict[str, Port] = field(default_factory=dict)
    port_order: list[str] = field(default_factory=list)
    wires: set[str] = field(default_factory=set)
    instances: list[Instance] = field(default_factory=list)
    has_behavioral: bool = False  # contains always/assign/initial
    notes: list[str] = field(default_factory=list)


# ----------------------------- preprocessing -------------------------------- #

def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def strip_attributes(text: str) -> str:
    return re.sub(r"\(\*.*?\*\)", "", text, flags=re.DOTALL)


def strip_directives(text: str) -> str:
    return re.sub(r"^\s*`[a-zA-Z_]\w*[^\n]*$", "", text, flags=re.MULTILINE)


def preprocess(text: str) -> str:
    text = strip_comments(text)
    text = strip_attributes(text)
    text = strip_directives(text)
    return text


# ----------------------------- module extraction ---------------------------- #

MODULE_RE = re.compile(r"\bmodule\b\s+([A-Za-z_][\w$]*)\s*(?:#\s*\(.*?\))?\s*\(([^;]*)\)\s*;", re.DOTALL)
ENDMODULE_RE = re.compile(r"\bendmodule\b")


def split_modules(text: str) -> list[tuple[str, str, str]]:
    """Return list of (module_name, port_list_raw, module_body_text)."""
    out: list[tuple[str, str, str]] = []
    pos = 0
    while True:
        m = MODULE_RE.search(text, pos)
        if not m:
            break
        e = ENDMODULE_RE.search(text, m.end())
        if not e:
            break
        body = text[m.end(): e.start()]
        out.append((m.group(1), m.group(2), body))
        pos = e.end()
    return out


PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*"
    r"(?:\[\s*([-\w` ]+)\s*:\s*([-\w` ]+)\s*\])?\s*"
    r"([\w$,\s]+?)\s*;",
    re.MULTILINE,
)

WIRE_DECL_RE = re.compile(
    r"\b(?:wire|reg|logic)\b\s*"
    r"(?:\[\s*([-\w` ]+)\s*:\s*([-\w` ]+)\s*\])?\s*"
    r"([\w$,\s]+?)\s*;",
    re.MULTILINE,
)

# Match: CellType inst_name ( .pin(net), .pin2(net2) );
INSTANCE_RE = re.compile(
    r"\b([A-Za-z_][\w$]*)\s+([A-Za-z_][\w$\[\]]*)\s*\(\s*((?:\.[\w$]+\s*\([^)]*\)\s*,?\s*)+)\)\s*;",
    re.MULTILINE,
)

PIN_RE = re.compile(r"\.([\w$]+)\s*\(\s*([^)]*?)\s*\)")

BEHAVIORAL_RE = re.compile(r"\b(always|assign|initial|generate|function|task)\b")


def parse_int_safe(s) -> int | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_ports(name: str, port_list_raw: str, body: str) -> Module:
    mod = Module(name=name)
    mod.has_behavioral = bool(BEHAVIORAL_RE.search(body))

    # Collect declared port directions first
    declared: dict[str, Port] = {}
    for dirn, msb_s, lsb_s, names in PORT_DECL_RE.findall(body + ";") + PORT_DECL_RE.findall(port_list_raw + ";"):
        msb = parse_int_safe(msb_s)
        lsb = parse_int_safe(lsb_s)
        width = 1 if msb is None or lsb is None else abs(msb - lsb) + 1
        for nm in names.split(","):
            nm = nm.strip()
            if not nm:
                continue
            declared[nm] = Port(
                name=nm, direction=dirn,
                width=width,
                msb=msb if msb is not None else 0,
                lsb=lsb if lsb is not None else 0,
            )

    # Use the port_list_raw to establish order
    order: list[str] = []
    for raw in port_list_raw.split(","):
        raw = raw.strip()
        if not raw:
            continue
        toks = raw.split()
        cand = toks[-1].strip("[]")
        cand = re.sub(r"\[.*\]", "", cand)
        if cand in declared:
            order.append(cand)
        elif cand:
            # ANSI-style: `input wire foo` appears in the port list itself
            ansi = re.match(r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(?:\[\s*([-\w` ]+)\s*:\s*([-\w` ]+)\s*\])?\s*([A-Za-z_][\w$]*)", raw)
            if ansi:
                nm = ansi.group(4)
                msb = parse_int_safe(ansi.group(2))
                lsb = parse_int_safe(ansi.group(3))
                width = 1 if msb is None or lsb is None else abs(msb - lsb) + 1
                declared[nm] = Port(name=nm, direction=ansi.group(1), width=width,
                                    msb=msb or 0, lsb=lsb or 0)
                order.append(nm)
            else:
                order.append(cand)

    mod.ports = declared
    mod.port_order = order

    # wires
    for msb_s, lsb_s, names in WIRE_DECL_RE.findall(body):
        for nm in names.split(","):
            nm = nm.strip()
            if nm and nm not in mod.ports:
                mod.wires.add(nm)

    # instances
    for cell_type, inst_name, pin_block in INSTANCE_RE.findall(body):
        if cell_type in {"input", "output", "inout", "wire", "reg", "logic", "assign",
                         "always", "initial", "generate", "endgenerate", "if", "else",
                         "case", "endcase", "begin", "end", "module", "endmodule",
                         "parameter", "localparam", "function", "task"}:
            continue
        inst = Instance(inst_name=inst_name, cell_type=cell_type)
        for pin, net in PIN_RE.findall(pin_block):
            inst.connections[pin] = net.strip()
        mod.instances.append(inst)

    return mod


def parse_file(path: Path) -> dict[str, Module]:
    text = preprocess(path.read_text(errors="replace"))
    modules: dict[str, Module] = {}
    for name, ports_raw, body in split_modules(text):
        modules[name] = parse_ports(name, ports_raw, body)
    return modules


# ----------------------------- analysis ------------------------------------- #

def infer_top(modules: dict[str, Module], explicit: str | None) -> str:
    if explicit:
        if explicit not in modules:
            raise SystemExit(f"--top {explicit} not found among modules: {sorted(modules)}")
        return explicit
    instantiated: set[str] = set()
    for m in modules.values():
        for inst in m.instances:
            if inst.cell_type in modules:
                instantiated.add(inst.cell_type)
    roots = [n for n in modules if n not in instantiated]
    if len(roots) == 1:
        return roots[0]
    if not roots:
        # all are instantiated by someone (cycle?) — fall back to most-instances
        return max(modules, key=lambda n: len(modules[n].instances))
    # multiple roots: prefer the one with most instances
    roots.sort(key=lambda n: -len(modules[n].instances))
    return roots[0]


def build_hierarchy(modules: dict[str, Module], top: str, max_depth: int = 10000) -> dict:
    def walk(mod_name: str, depth: int) -> dict:
        if depth > max_depth or mod_name not in modules:
            return {"module": mod_name, "instances": [], "leaf_cell_count": 0,
                    "leaf_cell_counter": {}}
        node = {"module": mod_name, "instances": [], "leaf_cell_count": 0,
                "leaf_cell_counter": defaultdict(int)}
        for inst in modules[mod_name].instances:
            if inst.cell_type in modules:
                child = walk(inst.cell_type, depth + 1)
                child["inst_name"] = inst.inst_name
                node["instances"].append(child)
                node["leaf_cell_count"] += child["leaf_cell_count"]
                for k, v in child["leaf_cell_counter"].items():
                    node["leaf_cell_counter"][k] += v
            else:
                node["leaf_cell_count"] += 1
                node["leaf_cell_counter"][inst.cell_type] += 1
        # Collapse direct leaf-cell children into a per-type summary list. We
        # also track total local-leaf-cell-instance count so the renderer can
        # decide whether to print individual instances or a summary line.
        local_leaves = {}
        for inst in modules[mod_name].instances:
            if inst.cell_type not in modules:
                local_leaves.setdefault(inst.cell_type, []).append(inst.inst_name)
        node["local_leaves"] = local_leaves
        node["leaf_cell_counter"] = dict(node["leaf_cell_counter"])
        return node
    return walk(top, 0)


def is_sequential(cell_type: str, conns: dict[str, str]) -> bool:
    if SEQ_CELL_RE.search(cell_type):
        return True
    return any(p in SEQ_CK_PINS for p in conns)


def clock_like_pins(cell_type: str, conns: dict[str, str]) -> list[str]:
    """Return pin names on this instance that act as a clock / latch-enable.

    For latches (matched by LATCH_CELL_RE) we accept the wider LATCH_EN_PINS
    set (E/EN/G/GATE). For all other cells we only count strict clock pins.
    Returns each clock-like pin once. Some macro cells (register banks) may
    expose multiple clock pins — they all count.
    """
    pins = []
    is_latch = bool(LATCH_CELL_RE.match(cell_type))
    for pin in conns:
        if pin in SEQ_CK_PINS:
            pins.append(pin)
        elif is_latch and pin in LATCH_EN_PINS:
            pins.append(pin)
    return pins


def build_flat_graph(modules: dict[str, Module], top: str) -> dict:
    """Build a flat net-level graph from the top module (no hierarchy flattening of
    sub-modules — those are treated as black boxes here; logic depth is computed
    against the top module's leaf cells only). For deep hierarchical netlists,
    the user should flatten in synthesis or use Innovus DB path.
    """
    top_mod = modules[top]
    # If top module contains sub-modules, we still walk inside them when they
    # are defined locally — but to keep this scalable we only walk the top
    # module's own instances. Hierarchical depth is reported separately.
    drivers: dict[str, list[tuple[Instance, str]]] = defaultdict(list)  # net -> [(inst, pin)]
    loads: dict[str, list[tuple[Instance, str]]] = defaultdict(list)
    seq_insts: list[Instance] = []
    comb_insts: list[Instance] = []
    for inst in top_mod.instances:
        seq = is_sequential(inst.cell_type, inst.connections)
        (seq_insts if seq else comb_insts).append(inst)
        for pin, net in inst.connections.items():
            # output pins typically include Q, QN, ZN, Z, Y, CO, S; we don't
            # have a liberty file here, so heuristic: pins named Q/QN/Z/ZN/Y/CO/S/SUM/OUT
            if pin in {"Q", "QN", "Z", "ZN", "Y", "CO", "S", "SUM", "OUT"}:
                drivers[net].append((inst, pin))
            else:
                loads[net].append((inst, pin))
    return {
        "drivers": drivers,
        "loads": loads,
        "seq": seq_insts,
        "comb": comb_insts,
        "top": top_mod,
    }


def logic_levels(graph: dict) -> dict:
    """BFS combinational levels. Boundaries: primary inputs and sequential Q pins."""
    top_mod: Module = graph["top"]
    drivers = graph["drivers"]
    loads = graph["loads"]
    seq_insts: list[Instance] = graph["seq"]
    comb_insts: list[Instance] = graph["comb"]

    # Sources of level 0: PI ports + sequential Q nets + const
    inst_level: dict[str, int] = {}  # inst_name -> level
    net_level: dict[str, int] = {}
    queue: deque[str] = deque()

    for port_name, port in top_mod.ports.items():
        if port.direction == "input":
            for nm in expand_bus_net(port_name, port):
                net_level[nm] = 0
                queue.append(nm)
    for inst in seq_insts:
        for pin, net in inst.connections.items():
            if pin in {"Q", "QN"}:
                net_level[net] = 0
                queue.append(net)
    for c in CONST_NETS:
        net_level[c] = 0

    # Build comb-inst dependency: an inst is ready once all its input nets are
    # leveled; its output net then takes max(input_levels)+1.
    comb_inputs: dict[str, list[str]] = {}
    comb_outputs: dict[str, list[str]] = {}
    by_name: dict[str, Instance] = {}
    pending_inputs: dict[str, set[str]] = {}
    for inst in comb_insts:
        by_name[inst.inst_name] = inst
        ins, outs = [], []
        for pin, net in inst.connections.items():
            if pin in {"Q", "QN", "Z", "ZN", "Y", "CO", "S", "SUM", "OUT"}:
                outs.append(net)
            else:
                ins.append(net)
        comb_inputs[inst.inst_name] = ins
        comb_outputs[inst.inst_name] = outs
        pending_inputs[inst.inst_name] = set(ins)

    # Reverse map: net -> [inst names that consume it]
    net_to_consumers: dict[str, list[str]] = defaultdict(list)
    for nm, ins in comb_inputs.items():
        for net in ins:
            net_to_consumers[net].append(nm)

    iterations = 0
    while queue:
        iterations += 1
        if iterations > 10_000_000:
            break
        net = queue.popleft()
        lvl = net_level[net]
        for inst_name in net_to_consumers.get(net, []):
            pending = pending_inputs[inst_name]
            pending.discard(net)
            # compute partial max so far
            cur = inst_level.get(inst_name, -1)
            inst_level[inst_name] = max(cur, lvl + 1)
            if not pending:
                out_lvl = inst_level[inst_name]
                for out_net in comb_outputs[inst_name]:
                    prev = net_level.get(out_net, -1)
                    if out_lvl > prev:
                        net_level[out_net] = out_lvl
                        queue.append(out_net)

    # Anything still pending might be in a combinational loop or missing driver:
    unsettled = [n for n, p in pending_inputs.items() if p]
    return {
        "inst_level": inst_level,
        "net_level": net_level,
        "max_level": max(inst_level.values()) if inst_level else 0,
        "unsettled_insts": unsettled,
    }


def expand_bus_net(name: str, port: Port) -> list[str]:
    if port.width <= 1:
        return [name]
    # We don't expand bus to bit-blasted nets here; gate-level netlists are
    # typically already bit-blasted by synthesis. If not, the bus name is used
    # as a single net.
    return [name]


def port_fanin_fanout(graph: dict) -> dict:
    top_mod: Module = graph["top"]
    drivers = graph["drivers"]
    loads = graph["loads"]
    info: dict[str, dict] = {}
    bus_re_cache: dict[str, re.Pattern] = {}
    def matching_nets(pname: str, width: int, mp: dict) -> list:
        if width <= 1:
            return list(mp.get(pname, []))
        if pname not in bus_re_cache:
            bus_re_cache[pname] = re.compile(rf"^{re.escape(pname)}\s*(?:\[\s*\d+\s*\])?$")
        pat = bus_re_cache[pname]
        out_list = []
        for net, entries in mp.items():
            if pat.match(net):
                out_list.extend(entries)
        return out_list

    for pname in top_mod.port_order or list(top_mod.ports):
        port = top_mod.ports.get(pname)
        if port is None:
            continue
        first_loads = [(i.inst_name, i.cell_type, pin) for (i, pin) in matching_nets(pname, port.width, loads)]
        first_drivers = [(i.inst_name, i.cell_type, pin) for (i, pin) in matching_nets(pname, port.width, drivers)]
        info[pname] = {
            "direction": port.direction,
            "width": port.width,
            "drivers": first_drivers,
            "loads": first_loads,
        }
    return info


def clock_reset_tree(graph: dict) -> dict:
    top_mod: Module = graph["top"]
    seq_insts: list[Instance] = graph["seq"]
    clocks: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    resets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for inst in seq_insts:
        for pin, net in inst.connections.items():
            if pin in SEQ_CK_PINS:
                clocks[net].append((inst.inst_name, inst.cell_type, pin))
            elif pin in SEQ_RST_PINS:
                resets[net].append((inst.inst_name, inst.cell_type, pin))
    # Also add any port whose name looks like clock/reset even if not yet attached
    for pname, port in top_mod.ports.items():
        if CLK_PORT_RE.match(pname) and pname not in clocks:
            clocks[pname] = clocks.get(pname, [])
        if RST_PORT_RE.match(pname) and pname not in resets:
            resets[pname] = resets.get(pname, [])
    return {"clocks": dict(clocks), "resets": dict(resets)}


def hierarchical_clock_reset(modules: dict[str, Module], top: str) -> dict:
    """Walk the full hierarchy and accumulate per-top-port fanout for clock and
    reset signals.

    For each module we maintain `port_to_top`: a map from the current module's
    port name to the top-level port name that ultimately drives (or sinks) it.
    When entering a sub-module via an instance, we rebuild `port_to_top` for
    the child using the parent's net→top-port resolution.

    Sequential cells inside any sub-module contribute their CK/RST connections
    to a top-level clock/reset bucket (or to an `<internal>` bucket if the
    net does not chain back to a top port).
    """
    clocks: dict[str, int] = defaultdict(int)
    resets: dict[str, int] = defaultdict(int)
    # Per-net breakdown for nets that didn't resolve to a top-level port,
    # keyed by the deepest local net name. The walker prefers the most-local
    # qualified name (which often equals the pulse-gen output that locally
    # creates the clock); this gives the user something actionable when the
    # design has internally generated clocks.
    internal_clocks: dict[str, int] = defaultdict(int)
    internal_resets: dict[str, int] = defaultdict(int)
    cell_count_total = 0
    seq_count_total = 0

    INTERNAL = "__internal__"

    def walk(mod_name: str, path: str, port_to_top: dict[str, str], depth: int):
        nonlocal cell_count_total, seq_count_total
        if depth > 200 or mod_name not in modules:
            return
        mod = modules[mod_name]
        # Build a local map: net_in_this_module -> top_port_name (or INTERNAL)
        # Starts with the explicit port_to_top map.
        net_to_top: dict[str, str] = dict(port_to_top)

        for inst in mod.instances:
            cell_count_total += 1
            if inst.cell_type in modules:
                # Build child's port_to_top by resolving each connection's net.
                child_port_to_top: dict[str, str] = {}
                for pin, net in inst.connections.items():
                    # Strip bus selector for the resolution lookup.
                    base = re.sub(r"\[.*\]$", "", net)
                    if net in net_to_top:
                        child_port_to_top[pin] = net_to_top[net]
                    elif base in net_to_top:
                        child_port_to_top[pin] = net_to_top[base]
                    else:
                        child_port_to_top[pin] = INTERNAL
                walk(inst.cell_type, path + "/" + inst.inst_name,
                     child_port_to_top, depth + 1)
            else:
                # Leaf cell — inspect for clock/reset pin connections.
                if is_sequential(inst.cell_type, inst.connections):
                    seq_count_total += 1
                ck_pins = clock_like_pins(inst.cell_type, inst.connections)
                for pin in ck_pins:
                    net = inst.connections[pin]
                    base = re.sub(r"\[.*\]$", "", net)
                    top_drv = net_to_top.get(net) or net_to_top.get(base) or INTERNAL
                    clocks[top_drv] += 1
                    if top_drv == INTERNAL:
                        internal_clocks[base] += 1
                for pin, net in inst.connections.items():
                    if pin in SEQ_RST_PINS:
                        base = re.sub(r"\[.*\]$", "", net)
                        top_drv = net_to_top.get(net) or net_to_top.get(base) or INTERNAL
                        resets[top_drv] += 1
                        if top_drv == INTERNAL:
                            internal_resets[base] += 1

    # Seed top-level port_to_top: each top port maps to itself.
    top_mod = modules[top]
    seed = {p: p for p in top_mod.ports}
    walk(top, top, seed, 0)

    # Make sure top-named clock/reset ports show up even with zero fanout.
    for pname in top_mod.ports:
        if CLK_PORT_RE.match(pname) and pname not in clocks:
            clocks[pname] = 0
        if RST_PORT_RE.match(pname) and pname not in resets:
            resets[pname] = 0
    return {
        "clocks": dict(clocks),
        "resets": dict(resets),
        "internal_clocks": dict(internal_clocks),
        "internal_resets": dict(internal_resets),
        "cell_count_total": cell_count_total,
        "seq_count_total": seq_count_total,
    }


# ----------------------------- rendering ------------------------------------ #

def render_report(
    netlist_path: Path,
    modules: dict[str, Module],
    top: str,
    hierarchy: dict,
    levels: dict | None,
    pfan: dict,
    cktree: dict,
    detected_format: str,
    leaf_collapse: int = 4,
    hier_max_depth: int | None = None,
) -> str:
    top_mod = modules[top]
    n_ports_in = sum(1 for p in top_mod.ports.values() if p.direction == "input")
    n_ports_out = sum(1 for p in top_mod.ports.values() if p.direction == "output")
    n_ports_io = sum(1 for p in top_mod.ports.values() if p.direction == "inout")
    n_leaf_total = hierarchy.get("leaf_cell_count", 0)

    out: list[str] = []
    out.append(f"# Netlist Analysis Report — `{netlist_path.name}`\n")

    # Section 1
    out.append("## 1. Summary\n")
    out.append(f"- **Source file**: `{netlist_path}`")
    out.append(f"- **Detected format**: {detected_format}")
    out.append(f"- **Top module**: `{top}`")
    out.append(f"- **Modules defined**: {len(modules)}")
    out.append(f"- **Top-level instances**: {len(top_mod.instances)}")
    out.append(f"- **Total leaf-cell count (recursive)**: {n_leaf_total}")
    out.append(f"- **Top ports**: {len(top_mod.ports)} (input={n_ports_in}, output={n_ports_out}, inout={n_ports_io})")
    if levels is not None:
        out.append(f"- **Max combinational logic depth**: {levels['max_level']}")
    out.append(f"- **Detected clocks**: {len(cktree['clocks'])}")
    out.append(f"- **Detected resets**: {len(cktree['resets'])}")
    out.append("")

    # Section 2 — port table
    out.append("## 2. Top-level Port Table\n")
    out.append("| # | Port | Dir | Width | MSB:LSB |")
    out.append("|---|------|-----|-------|---------|")
    for i, pname in enumerate(top_mod.port_order, 1):
        p = top_mod.ports.get(pname)
        if not p:
            continue
        bus = f"[{p.msb}:{p.lsb}]" if p.width > 1 else "—"
        out.append(f"| {i} | `{p.name}` | {p.direction} | {p.width} | {bus} |")
    out.append("")

    # Section 3 — hierarchy
    out.append("## 3. Hierarchy Tree\n")
    if hier_max_depth is not None:
        out.append(f"_Depth-limited render (max depth = {hier_max_depth}); leaf cells with > {leaf_collapse} sibs of same type are collapsed._\n")
    else:
        out.append(f"_Leaf cells with > {leaf_collapse} sibs of same type are collapsed into a `Cell × N` summary._\n")
    out.append("```")
    render_tree(hierarchy, out, prefix="", is_last=True, top_name=True,
                leaf_collapse=leaf_collapse, max_depth=hier_max_depth)
    out.append("```")
    out.append("")
    out.append("### Module instantiation count (defined modules)\n")
    out.append("| Module | Instantiated N× across design |")
    out.append("|--------|-------------------------------|")
    counter: dict[str, int] = defaultdict(int)
    def count_mods(node: dict):
        counter[node["module"]] += 1
        for c in node.get("instances", []):
            count_mods(c)
    count_mods(hierarchy)
    for mod_name, n in sorted(counter.items(), key=lambda kv: -kv[1]):
        out.append(f"| `{mod_name}` | {n} |")
    out.append("")
    # Leaf-cell-type histogram
    leaf_hist = hierarchy.get("leaf_cell_counter", {})
    if leaf_hist:
        out.append("### Leaf cell histogram (by cell type)\n")
        out.append("| Cell type | Count |")
        out.append("|-----------|-------|")
        for ct, n in sorted(leaf_hist.items(), key=lambda kv: -kv[1])[:30]:
            out.append(f"| `{ct}` | {n} |")
        if len(leaf_hist) > 30:
            out.append(f"| _… {len(leaf_hist) - 30} more cell types_ | — |")
        out.append("")

    # Section 4 — logic depth
    out.append("## 4. Logic Depth (Combinational Levels)\n")
    if levels is None:
        out.append("Skipped — netlist appears to be behavioral RTL (contains `always`/`assign`). ")
        out.append("Re-run on a synthesized gate-level netlist for logic-depth analysis.\n")
    else:
        out.append(f"- **Method**: BFS from primary inputs and sequential Q pins, levels propagate through combinational cells (boundary at sequential CK/D).")
        out.append(f"- **Max combinational depth observed at top level**: {levels['max_level']}")
        out.append(f"- **Unsettled combinational instances** (possible loop or missing driver): {len(levels['unsettled_insts'])}")
        if levels["inst_level"]:
            top10 = sorted(levels["inst_level"].items(), key=lambda kv: -kv[1])[:10]
            out.append("\n### Top 10 deepest combinational instances\n")
            out.append("| Rank | Instance | Level |")
            out.append("|------|----------|-------|")
            for r, (nm, lv) in enumerate(top10, 1):
                out.append(f"| {r} | `{nm}` | {lv} |")
        if levels["unsettled_insts"][:5]:
            out.append("\n### Unsettled instances (first 5)\n")
            for nm in levels["unsettled_insts"][:5]:
                out.append(f"- `{nm}`")
        out.append("")

    # Section 5 — port fanin/fanout
    out.append("## 5. Port Fanin / Fanout\n")
    out.append("| Port | Dir | First-level connections (inst.pin · cell) |")
    out.append("|------|-----|-------------------------------------------|")
    for pname, info in pfan.items():
        endpoints = info["drivers"] if info["direction"] == "output" else info["loads"]
        if not endpoints:
            cell_list = "_(no connection found at top level)_"
        else:
            shown = endpoints[:8]
            cell_list = ", ".join(f"`{i}.{pin}` (`{c}`)" for i, c, pin in shown)
            if len(endpoints) > 8:
                cell_list += f" … +{len(endpoints)-8} more"
        out.append(f"| `{pname}` | {info['direction']} | {cell_list} |")
    out.append("")

    # Section 6 — clock & reset tree (hierarchical)
    out.append("## 6. Clock & Reset Tree\n")
    use_hier = "hier" in cktree
    if use_hier:
        h = cktree["hier"]
        out.append(f"_Hierarchical walk over {h['cell_count_total']} instances "
                   f"({h['seq_count_total']} sequential leaves).  "
                   f"Counts are sequential-pin loads chained to the named top-level port._\n")
    out.append("### Clocks\n")
    clock_view = cktree["hier"]["clocks"] if use_hier else {k: len(v) for k, v in cktree["clocks"].items()}
    if not clock_view or all(v == 0 for v in clock_view.values()):
        out.append("_(no clock fanout resolved to a top-level port — heuristic failed or pure-combinational; "
                   "pass `--clock-pattern` to override)_\n")
    else:
        out.append("| Top-level clock port | Sequential-cell fanout |")
        out.append("|----------------------|------------------------|")
        for port_name, n in sorted(clock_view.items(), key=lambda kv: -kv[1]):
            if port_name == "__internal__":
                out.append(f"| _(internal nets — see breakdown below)_ | {n} |")
            else:
                out.append(f"| `{port_name}` | {n} |")
        out.append("")
        if use_hier and cktree["hier"].get("internal_clocks"):
            out.append("**Internal clock nets** (locally generated clocks — typically pulse-gen, clock-gating, "
                       "or pipelined gated clocks; not reaching a top port):\n")
            out.append("| Internal net | Sequential-cell fanout |")
            out.append("|--------------|------------------------|")
            items = sorted(cktree["hier"]["internal_clocks"].items(), key=lambda kv: -kv[1])
            for net, n in items[:25]:
                out.append(f"| `{net}` | {n} |")
            if len(items) > 25:
                out.append(f"| _… {len(items) - 25} more internal clock nets_ | — |")
            out.append("")
    out.append("### Resets\n")
    reset_view = cktree["hier"]["resets"] if use_hier else {k: len(v) for k, v in cktree["resets"].items()}
    if not reset_view or all(v == 0 for v in reset_view.values()):
        out.append("_(no reset fanout detected — design may not use a sync reset, or reset signal name "
                   "is unusual; pass `--reset-pattern` to override)_\n")
    else:
        out.append("| Top-level reset port | Sequential-cell fanout |")
        out.append("|----------------------|------------------------|")
        for port_name, n in sorted(reset_view.items(), key=lambda kv: -kv[1]):
            if port_name == "__internal__":
                out.append(f"| _(internal nets — see breakdown below)_ | {n} |")
            else:
                out.append(f"| `{port_name}` | {n} |")
        out.append("")
        if use_hier and cktree["hier"].get("internal_resets"):
            out.append("**Internal reset nets**:\n")
            out.append("| Internal net | Sequential-cell fanout |")
            out.append("|--------------|------------------------|")
            items = sorted(cktree["hier"]["internal_resets"].items(), key=lambda kv: -kv[1])
            for net, n in items[:25]:
                out.append(f"| `{net}` | {n} |")
            out.append("")

    # Section 7 — notes
    out.append("## 7. Notes & Limitations\n")
    notes = []
    if detected_format.startswith("RTL"):
        notes.append("Input contains behavioral RTL constructs (`always`/`assign`/...). "
                     "Hierarchy and port info are best-effort lexical; logic depth was skipped.")
    if levels and levels["unsettled_insts"]:
        notes.append(f"{len(levels['unsettled_insts'])} combinational instance(s) could not be leveled — "
                     "may indicate combinational loop or unconnected driver.")
    if not cktree["clocks"]:
        notes.append("No clock signal detected by the default heuristic. If the netlist uses a non-standard "
                     "naming, re-run with `--clock-pattern '<regex>'`.")
    notes.append("This analyzer is a lexical/regex parser, not a full Verilog frontend. "
                 "Unusual constructs (deep `defparam`, complex `generate`, multi-line bus expressions) "
                 "may not be captured. Verify against synthesis logs for production sign-off.")
    for n in notes:
        out.append(f"- {n}")
    out.append("")

    return "\n".join(out)


def render_tree(node: dict, out: list[str], prefix: str, is_last: bool, top_name: bool,
                leaf_collapse: int = 4, max_depth: int | None = None, _depth: int = 0):
    """Render hierarchy. Non-leaf (sub-module) children are listed individually.
    Leaf cells inside the same parent are collapsed by cell type into a single
    summary line when there are more than `leaf_collapse` of the same type, so
    the tree stays readable on real netlists.
    """
    if top_name:
        out.append(f"{node.get('module', '?')}")
    if max_depth is not None and _depth >= max_depth:
        if node.get("leaf_cell_count"):
            out.append(f"{prefix}└── … (depth cap reached; {node['leaf_cell_count']} leaf cells below)")
        return
    sub_children = [c for c in node.get("instances", []) if not c.get("is_leaf")]
    local_leaves: dict[str, list[str]] = node.get("local_leaves", {}) or {}
    leaf_total = sum(len(v) for v in local_leaves.values())
    items: list[tuple[str, dict | None, str, int]] = []  # (kind, child_or_None, label, count)
    for c in sub_children:
        items.append(("submod", c, "", 1))
    for cell_type, insts in local_leaves.items():
        if len(insts) <= leaf_collapse:
            for inst_name in insts:
                items.append(("leaf_inst", None, f"{inst_name} ({cell_type})", 1))
        else:
            items.append(("leaf_group", None, f"{cell_type} × {len(insts)}", len(insts)))

    for i, (kind, child, label, n) in enumerate(items):
        last = (i == len(items) - 1)
        branch = "└── " if last else "├── "
        if kind == "submod":
            out.append(f"{prefix}{branch}{child['inst_name']} ({child['module']})")
            next_prefix = prefix + ("    " if last else "│   ")
            render_tree(child, out, next_prefix, last, top_name=False,
                        leaf_collapse=leaf_collapse, max_depth=max_depth, _depth=_depth + 1)
        elif kind == "leaf_inst":
            out.append(f"{prefix}{branch}{label}  [leaf]")
        else:
            out.append(f"{prefix}{branch}{label}  [leaf]")


# ----------------------------- driver --------------------------------------- #

def detect_format(netlist_path: Path, modules: dict[str, Module], top: str) -> str:
    if modules[top].has_behavioral:
        return "RTL Verilog (behavioral constructs detected)"
    return "Gate-level Verilog"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verilog netlist structural analyzer")
    ap.add_argument("--netlist", required=True, help="Path to .v / .vg / .gv file")
    ap.add_argument("--top", default=None, help="Top module name (auto-inferred if omitted)")
    ap.add_argument("--output", default=None, help="Output Markdown path (default: <netlist>_analysis.md)")
    ap.add_argument("--max-depth", type=int, default=10000)
    ap.add_argument("--clock-pattern", default=None, help="Regex override for clock port detection")
    ap.add_argument("--seq-pattern", default=None, help="Regex override for sequential cell name detection")
    ap.add_argument("--reset-pattern", default=None, help="Regex override for reset port detection")
    ap.add_argument("--leaf-collapse", type=int, default=4,
                    help="When a parent has more than N leaf children of the same cell type, collapse to a summary line (default 4)")
    ap.add_argument("--hier-max-depth", type=int, default=None,
                    help="Cap hierarchy-tree render depth (default: no cap)")
    ap.add_argument("--json", action="store_true", help="Also dump intermediate JSON next to the report")
    args = ap.parse_args(argv)

    global CLK_PORT_RE, RST_PORT_RE, SEQ_CELL_RE
    if args.clock_pattern:
        CLK_PORT_RE = re.compile(args.clock_pattern, re.IGNORECASE)
    if args.reset_pattern:
        RST_PORT_RE = re.compile(args.reset_pattern, re.IGNORECASE)
    if args.seq_pattern:
        SEQ_CELL_RE = re.compile(args.seq_pattern, re.IGNORECASE)

    netlist_path = Path(args.netlist).expanduser()
    if not netlist_path.exists():
        print(f"ERROR: netlist file not found: {netlist_path}", file=sys.stderr)
        return 2

    modules = parse_file(netlist_path)
    if not modules:
        print("ERROR: no modules parsed (is this a Verilog file?)", file=sys.stderr)
        return 3

    top = infer_top(modules, args.top)
    fmt = detect_format(netlist_path, modules, top)
    hierarchy = build_hierarchy(modules, top, max_depth=args.max_depth)

    graph = build_flat_graph(modules, top)
    pfan = port_fanin_fanout(graph)
    cktree = clock_reset_tree(graph)
    cktree["hier"] = hierarchical_clock_reset(modules, top)
    levels = None
    if not modules[top].has_behavioral:
        levels = logic_levels(graph)

    report = render_report(netlist_path, modules, top, hierarchy, levels, pfan, cktree, fmt,
                           leaf_collapse=args.leaf_collapse, hier_max_depth=args.hier_max_depth)

    out_path = Path(args.output) if args.output else netlist_path.with_name(netlist_path.stem + "_analysis.md")
    out_path.write_text(report)

    if args.json:
        intermediate = {
            "source": str(netlist_path),
            "top": top,
            "format": fmt,
            "modules": list(modules),
            "hierarchy": hierarchy,
            "max_logic_level": levels["max_level"] if levels else None,
            "clocks": {k: len(v) for k, v in cktree["clocks"].items()},
            "resets": {k: len(v) for k, v in cktree["resets"].items()},
        }
        out_path.with_suffix(".json").write_text(json.dumps(intermediate, indent=2))

    print(f"Wrote report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
