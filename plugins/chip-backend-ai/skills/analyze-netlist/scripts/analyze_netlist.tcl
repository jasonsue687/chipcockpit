# analyze_netlist.tcl — Innovus path for the analyze-netlist skill.
#
# Usage:
#   innovus -no_gui -nolog -nowin -files analyze_netlist.tcl \
#       -overwrite -log /tmp/analyze_netlist.log
#
# Expectations:
#   - The design has already been loaded (read_db <path>) before invoking,
#     OR the env vars below are set so this script can load it:
#       ANALYZE_NETLIST_DB     : path to an Innovus design DB (.enc.dat dir)
#       ANALYZE_NETLIST_OUTPUT : where to write the Markdown report
#       ANALYZE_NETLIST_TOP    : (optional) override top design name
#
# The script extracts the four analysis dimensions using dbGet and writes a
# JSON file. A small Python renderer (render_report.py) is then invoked to
# convert that JSON into the final Markdown report.

if {[info exists ::env(ANALYZE_NETLIST_DB)]} {
    set _db $::env(ANALYZE_NETLIST_DB)
    if {[file exists $_db]} {
        puts "ANALYZE_NETLIST: read_db $_db"
        read_db $_db
    } else {
        puts "ANALYZE_NETLIST: WARNING — DB path $_db not found; assuming design already loaded"
    }
}

set out_path "/tmp/analyze_netlist_inter.json"
if {[info exists ::env(ANALYZE_NETLIST_OUTPUT)]} {
    set out_path $::env(ANALYZE_NETLIST_OUTPUT)
}

set top_name [dbGet top.name]
if {[info exists ::env(ANALYZE_NETLIST_TOP)] && $::env(ANALYZE_NETLIST_TOP) ne ""} {
    set top_name $::env(ANALYZE_NETLIST_TOP)
}

# ---- 1. Top-level ports ----------------------------------------------------
set ports [list]
foreach term [dbGet -p top.terms] {
    set pname [dbGet $term.name]
    set pdir  [dbGet $term.direction]
    set pwidth 1
    if {[regexp {\[(\d+):(\d+)\]} $pname _ msb lsb]} {
        set pwidth [expr {abs($msb - $lsb) + 1}]
    }
    lappend ports [list $pname $pdir $pwidth]
}

# ---- 2. Hierarchy (one level — Innovus keeps logical hierarchy in inst names)
# dbGet top.hInsts returns top-level hierarchical instances; .insts is leaves.
set hier_insts [list]
catch {
    foreach hi [dbGet -p top.hInsts] {
        lappend hier_insts [list [dbGet $hi.name] [dbGet $hi.cell.name] [llength [dbGet $hi.insts -default {}]]]
    }
}

# ---- 3. Logic depth ---------------------------------------------------------
# Use report_timing for max combinational depth across worst path levels.
# Note: requires that timing is loadable; fall back to "n/a" if not.
set max_levels "n/a"
catch {
    set tinfo [report_timing -nworst 1 -collection]
    if {$tinfo ne ""} {
        set max_levels [llength [get_property $tinfo cells]]
    }
}

# ---- 4. Port fanin/fanout ---------------------------------------------------
set port_fanout [list]
foreach term [dbGet -p top.terms] {
    set pname [dbGet $term.name]
    set pdir  [dbGet $term.direction]
    set loads [list]
    catch {
        foreach pin [dbGet [dbGet $term.net].allTerms -e] {
            set inst [dbGet $pin.inst.name -e ""]
            set pn   [dbGet $pin.name -e ""]
            if {$inst ne "" && $inst ne $pname} {
                lappend loads [list $inst $pn]
            }
        }
    }
    lappend port_fanout [list $pname $pdir $loads]
}

# ---- 5. Clock & reset tree --------------------------------------------------
set clocks [list]
catch {
    foreach clk [all_clocks] {
        set net [get_property $clk sources]
        set fanout_count 0
        catch { set fanout_count [llength [dbGet -p [dbGet $net.allTerms -e] -e]] }
        lappend clocks [list [get_property $clk name] $fanout_count]
    }
}

set resets [list]
foreach term [dbGet -p top.terms] {
    set pname [dbGet $term.name]
    if {[regexp -nocase {^(rst|reset|.*_rst|.*_reset|.*_rstn|.*_resetn|.*_nreset|rst_n|reset_n)$} $pname]} {
        set net [dbGet $term.net.name -e ""]
        set fanout 0
        catch { set fanout [llength [dbGet $term.net.allTerms -e]] }
        lappend resets [list $pname $fanout]
    }
}

# ---- Emit JSON --------------------------------------------------------------
proc json_str {s} { return "\"[string map {\\ \\\\ \" \\\"} $s]\"" }
proc json_list_strs {lst} {
    set parts [list]
    foreach x $lst { lappend parts [json_str $x] }
    return "\[[join $parts ,]\]"
}

set fp [open $out_path w]
puts $fp "{"
puts $fp "  \"source\": [json_str "innovus_db:$top_name"],"
puts $fp "  \"top\": [json_str $top_name],"
puts $fp "  \"format\": \"Innovus DB\","
# ports
set port_json [list]
foreach p $ports {
    lassign $p nm dir w
    lappend port_json "{[json_str name]:[json_str $nm],[json_str dir]:[json_str $dir],[json_str width]:$w}"
}
puts $fp "  \"ports\": \[[join $port_json ,]\],"
# hierarchy (one level)
set hier_json [list]
foreach h $hier_insts {
    lassign $h inm cell n
    lappend hier_json "{[json_str inst]:[json_str $inm],[json_str cell]:[json_str $cell],[json_str leaf_count]:$n}"
}
puts $fp "  \"hierarchy\": \[[join $hier_json ,]\],"
puts $fp "  \"max_logic_level\": [json_str $max_levels],"
# clocks
set ck_json [list]
foreach c $clocks {
    lassign $c nm fo
    lappend ck_json "{[json_str clock]:[json_str $nm],[json_str fanout]:$fo}"
}
puts $fp "  \"clocks\": \[[join $ck_json ,]\],"
set rs_json [list]
foreach r $resets {
    lassign $r nm fo
    lappend rs_json "{[json_str reset]:[json_str $nm],[json_str fanout]:$fo}"
}
puts $fp "  \"resets\": \[[join $rs_json ,]\]"
puts $fp "}"
close $fp

puts "ANALYZE_NETLIST: wrote intermediate JSON to $out_path"
puts "ANALYZE_NETLIST: now run: python3 render_report.py --json $out_path --output <report.md>"
