# routing-procs.tcl
# Reusable EXAMPLE Tcl procs for simulated RDL routing.
# Source this file at the top of your routing script.
#
# Assumes the following globals are set by the caller:
#   obstacle_map   — list of {netname cx cy hw hh}
#   RDL_WIDTH      — wire width in µm (e.g. 10.0)
#   MIN_SPACE      — min spacing in µm (e.g. 3.0)
#   PITCH          — RDL_WIDTH + MIN_SPACE
#   OBS_HW         — RDL_WIDTH/2 + MIN_SPACE
#   RDL_LAYER      — layer name string (e.g. "EXAMPLE_RDL")
#   MAX_VSTEPS     — max steps in find_v_col search (e.g. 40)
#   MAX_HSTEPS     — max steps in find_h_lane search (e.g. 40)

proc dist2d {x1 y1 x2 y2} {
    expr {sqrt(($x2-$x1)*($x2-$x1)+($y2-$y1)*($y2-$y1))}
}

proc bump_center {b} {
    set raw [get_db $b .bbox]
    if {[llength $raw] == 1} { set raw [lindex $raw 0] }
    list [expr {([lindex $raw 0]+[lindex $raw 2])/2.0}] \
         [expr {([lindex $raw 1]+[lindex $raw 3])/2.0}]
}

proc rect_overlap {llx lly urx ury netname obs_list} {
    foreach obs $obs_list {
        set onet [lindex $obs 0]
        if {$onet ne "" && $onet eq $netname} { continue }
        set ocx [lindex $obs 1]; set ocy [lindex $obs 2]
        set ohw [lindex $obs 3]; set ohh [lindex $obs 4]
        if {$ocx-$ohw >= $urx} { continue }
        if {$ocx+$ohw <= $llx} { continue }
        if {$ocy-$ohh >= $ury} { continue }
        if {$ocy+$ohh <= $lly} { continue }
        return 1
    }
    return 0
}

proc h_blocked {x0 x1 hy netname obs_list ohw} {
    rect_overlap [expr {min($x0,$x1)-$ohw}] [expr {$hy-$ohw}] \
                 [expr {max($x0,$x1)+$ohw}] [expr {$hy+$ohw}] $netname $obs_list
}

proc v_blocked {vx y0 y1 netname obs_list ohw} {
    rect_overlap [expr {$vx-$ohw}] [expr {min($y0,$y1)-$ohw}] \
                 [expr {$vx+$ohw}] [expr {max($y0,$y1)+$ohw}] $netname $obs_list
}

proc diag_blocked {x0 y0 x1 y1 netname obs_list ohw} {
    rect_overlap [expr {min($x0,$x1)-$ohw}] [expr {min($y0,$y1)-$ohw}] \
                 [expr {max($x0,$x1)+$ohw}] [expr {max($y0,$y1)+$ohw}] $netname $obs_list
}
