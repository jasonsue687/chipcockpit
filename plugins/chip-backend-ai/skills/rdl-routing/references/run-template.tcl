# run_rdl_template.tcl
# EXAMPLE Innovus-like launch script for simulated RDL routing.
# All paths, cell names, and license settings are FAKE placeholders.
#
# Usage (EXAMPLE only — do not point at real foundry trees):
#   cd <work_dir>
#   # Do NOT hard-code a real license server in public trees.
#   # export LM_LICENSE_FILE=<your-private-license-config>
#   innovus -no_gui -init run_rdl_template.tcl > run_rdl.log 2>&1

win off
setMultiCpuUsage -localCpu 2

# ── Design netlist (EXAMPLE) ───────────────────────────────────────────────
setUserDataValue init_verilog       ./example_top.v
setUserDataValue init_top_cell      example_top
setUserDataValue init_import_mode   {-keepEmptyModule 1 -useLefDef56 1}

# ── LEF files (EXAMPLE relative paths only) ────────────────────────────────
setUserDataValue init_lef_file "
./tech/example_tech.lef \
./tech/example_bump.lef \
./tech/example_io.lef \
"

puts "INFO: === init_design (EXAMPLE) ==="
init_design

puts "INFO: === defIn example_bumps.def ==="
defIn ./example_bumps.def

puts "INFO: === defIn example_io_shapes.def ==="
defIn ./example_io_shapes.def

set rdl_script "./rdl_connect_example.tcl"
puts "INFO: === source $rdl_script ==="
if {[catch {source $rdl_script} err]} {
    puts "**ERROR: $err"
} else {
    puts "INFO: EXAMPLE RDL routing finished"
}
puts "INFO: === ALL DONE ==="
