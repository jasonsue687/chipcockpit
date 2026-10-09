###############################################################################
#  place_remaining_ports.tcl  (PHASE 2)
#
#  After place_lv_ports.tcl has fixed the 1342 ports that connect directly to
#  pipe38 / pipe41 LV cells, this script handles the remaining top-level
#  terms (those that reach an LV cell only through some intermediate logic).
#
#  Algorithm:
#     1. Read the DB. Terms whose pStatus is "fixed" / "placed" are the
#        phase-1 anchors.  Remember (y, layer, side, trackIdx) for each.
#     2. For every still-unplaced term, BFS the netlist up to BFS_MAX_HOPS
#        through inst.instTerms <-> net.instTerms edges. Skip nets whose
#        fanout > BFS_MAX_NET_FANOUT (clock / reset trees blow BFS otherwise).
#     3. Among all placed terms reachable, take the *closest-hop* group and
#        compute the median Y -> that becomes the desired Y for this port.
#     4. Search nearest free (track, layer) slot within +/- MAX_RELATED_DIST
#        on M4/M6/M8 - same multi-layer logic as phase 1.
#     5. editPin -fixedPin -snap TRACK -assign {xEdge y} -layer L.
#
#  Inputs:  example_top.floorplan.enc.dat already restored AND
#           lv_port_assign.tcl already sourced (so anchors are fixed).
#  Outputs:
#     custom_place/lv_port_remain_assign.tcl
#     custom_place/lv_port_remain_assign.rpt
#
#  Usage:   innovus> source custom_place/place_lv_ports.tcl
#           innovus> source custom_place/place_remaining_ports.tcl
###############################################################################

# ----------------------------------------------------------------- params --
set IO_LAYER_NAMES   [list M4 M6 M8]
set MAX_RELATED_DIST 2.0     ;# user spec: <=2um from related anchor
set BFS_MAX_HOPS     3
set BFS_MAX_NET_FANOUT 50    ;# skip nets with more loads (clk/reset/etc.)
set BFS_MAX_VISITS   3000    ;# total nets visited per port (safety)

set OUT_TCL          "custom_place/lv_port_remain_assign.tcl"
set OUT_RPT          "custom_place/lv_port_remain_assign.rpt"

# --------------------------------------------------- sanity: design loaded --
if {[catch {dbGet top.name} _topName] || $_topName eq "" || $_topName eq "0x0"} {
    error "No design loaded - run place_lv_ports.tcl first."
}
puts "INFO: phase2 starting on design '$_topName'"

# --------------------------------------------------- die / io edges --
set fBox  [dbGet top.fPlan.box]
set fFlat [concat {*}$fBox]
set xL [lindex $fFlat 0]
set yB [lindex $fFlat 1]
set xR [lindex $fFlat 2]
set yT [lindex $fFlat 3]
puts "INFO: IO box ( $xL , $yB ) - ( $xR , $yT )"

# --------------------------------------------- common Y-track grid for layers --
proc layerYTrack {layerName} {
    foreach tg [dbGet top.fPlan.tracks] {
        if {[dbGet $tg.dir] ne "y"} { continue }
        foreach lp [dbGet $tg.layers] {
            if {[dbGet $lp.name] eq $layerName} {
                return [list [dbGet $tg.start] [dbGet $tg.step] [dbGet $tg.numTracks]]
            }
        }
    }
    return [list]
}
array set GRID {}
foreach Ln $IO_LAYER_NAMES {
    set g [layerYTrack $Ln]
    if {[llength $g] != 3} { error "No dir=y track group on $Ln" }
    set GRID($Ln) $g
}
set BASE_STEP  [lindex $GRID([lindex $IO_LAYER_NAMES 0]) 1]
set BASE_START [lindex $GRID([lindex $IO_LAYER_NAMES 0]) 0]
set BASE_NUM   [lindex $GRID([lindex $IO_LAYER_NAMES 0]) 2]
set MAX_DELTA  [expr {int(floor($MAX_RELATED_DIST/$BASE_STEP))}]
puts "INFO: base grid step=$BASE_STEP num=$BASE_NUM ; +/-${MAX_RELATED_DIST}um -> +/-${MAX_DELTA} tracks"

proc yToIdx {y} {
    global BASE_START BASE_STEP BASE_NUM
    set i [expr {int(round(($y - $BASE_START)/$BASE_STEP))}]
    if {$i < 0}            { set i 0 }
    if {$i > $BASE_NUM-1}  { set i [expr {$BASE_NUM-1}] }
    return $i
}
proc idxToY {i} {
    global BASE_START BASE_STEP
    return [expr {$BASE_START + $i*$BASE_STEP}]
}

# --------------------- 1) inventory placed (anchor) ports + used slots --
# Slot key = "$side|$idx|$layer"   value = portName
array set USED  {}
array set ANCHOR {}   ;# anchor($port) = list {side y layer xEdge}
set numAnchored 0
foreach termPtr [dbGet top.terms] {
    set status [dbGet $termPtr.pStatus -e]
    if {$status ne "fixed" && $status ne "placed"} { continue }
    set name [dbGet $termPtr.name]
    set pt   [concat {*}[dbGet $termPtr.pt -e]]
    if {[llength $pt] < 2} { continue }
    set tx [lindex $pt 0]
    set ty [lindex $pt 1]
    set lyrPtr [dbGet $termPtr.layer -e]
    set lyrName ""
    if {$lyrPtr ne "" && $lyrPtr ne "0x0"} { set lyrName [dbGet $lyrPtr.name] }
    # Side: nearest of xL or xR
    set side L
    if {abs($tx - $xR) < abs($tx - $xL)} { set side R }
    set idx [yToIdx $ty]
    if {[lsearch -exact $::IO_LAYER_NAMES $lyrName] >= 0} {
        set USED("$side|$idx|$lyrName") $name
    }
    set ANCHOR($name) [list $side $ty $lyrName $tx]
    incr numAnchored
}
puts "INFO: anchored ports detected from DB = $numAnchored"

# --------------------- 2) collect unplaced top terms ------------------
set unplaced [list]
foreach termPtr [dbGet top.terms] {
    set name [dbGet $termPtr.name]
    if {[info exists ANCHOR($name)]} { continue }
    set status [dbGet $termPtr.pStatus -e]
    set dir    [dbGet $termPtr.direction -e]
    lappend unplaced [list $name $dir $termPtr $status]
}
puts "INFO: unplaced top terms = [llength $unplaced]"

# --------------------- 3a) direct-net centroid helper -----------------
# Last-resort: when BFS finds no anchor (clock / reset / scan_en / any net
# whose fanout exceeds BFS_MAX_NET_FANOUT), follow the *direct* loads/drivers
# on the port's net (no fanout cap) and return the median (X,Y) of every
# instTerm location on that net.  These ports still get placed "along the
# data flow" — just based on geographic centroid instead of anchor hops.
#
# Returns {xMed yMed count}.  count == 0 when the net has no instTerms.
proc directNetCentroid {termPtr} {
    set netPtr [dbGet $termPtr.net -e]
    if {$netPtr eq "" || $netPtr eq "0x0"} { return [list 0 0 0] }
    set xs [list]
    set ys [list]
    foreach iTerm [dbGet $netPtr.instTerms -e] {
        if {$iTerm eq "" || $iTerm eq "0x0"} { continue }
        set pt [concat {*}[dbGet $iTerm.pt -e]]
        if {[llength $pt] >= 2} {
            lappend xs [lindex $pt 0]
            lappend ys [lindex $pt 1]
        }
    }
    set n [llength $ys]
    if {$n == 0} { return [list 0 0 0] }
    set xs [lsort -real $xs]
    set ys [lsort -real $ys]
    set mx [lindex $xs [expr {$n/2}]]
    set my [lindex $ys [expr {$n/2}]]
    return [list $mx $my $n]
}

# --------------------- 3b) BFS helper ----------------------------------
proc bfsRelated {startTermPtr maxHops maxFanout maxVisits anchorArrName} {
    upvar $anchorArrName ANCHOR
    set startName [dbGet $startTermPtr.name]
    set startNet  [dbGet $startTermPtr.net -e]
    if {$startNet eq "" || $startNet eq "0x0"} { return [list] }

    set visited [dict create]
    set queue   [list [list $startNet 0]]
    set found   [list]
    set visits  0
    while {[llength $queue] > 0 && $visits < $maxVisits} {
        set head   [lindex $queue 0]
        set queue  [lrange $queue 1 end]
        lassign $head net hops
        if {[dict exists $visited $net]} { continue }
        dict set visited $net 1
        incr visits
        # Skip very-high-fanout (clock/reset spine)
        set numIT [llength [dbGet $net.instTerms -e]]
        if {$numIT > $maxFanout} { continue }
        # Collect any anchor port on this net
        foreach t [dbGet $net.terms -e] {
            if {$t eq "" || $t eq "0x0"} { continue }
            set pname [dbGet $t.name]
            if {$pname eq $startName} { continue }
            if {[info exists ANCHOR($pname)]} {
                lappend found [list $pname $hops]
            }
        }
        if {$hops >= $maxHops} { continue }
        # Expand through instTerms -> parent inst -> other instTerms -> nets
        foreach iTerm [dbGet $net.instTerms -e] {
            if {$iTerm eq "" || $iTerm eq "0x0"} { continue }
            set inst [dbGet $iTerm.inst -e]
            if {$inst eq "" || $inst eq "0x0"} { continue }
            foreach iTerm2 [dbGet $inst.instTerms -e] {
                set n2 [dbGet $iTerm2.net -e]
                if {$n2 ne "" && $n2 ne "0x0" && ![dict exists $visited $n2]} {
                    lappend queue [list $n2 [expr {$hops+1}]]
                }
            }
        }
    }
    return $found
}

# --------------------- 4) assign each unplaced port -------------------
# Every unplaced port MUST be placed. Strategy:
#   1) Try BFS to nearby same-side anchors -> use median anchor Y.
#   2) If BFS yields nothing (clock/reset/scan_en spine: too-high fanout),
#      fall back to the median Y of *all instTerm pts on this port's net*.
#      This is the "along the data flow" target for high-fanout signals.
#   3) If even the net has no loads (truly dangling), drop to die-center Y.
# For ports with no direction tag, pick the side closer to the net centroid X.
set results          [list]
set fallbackInputs   0
set fallbackOutputs  0
foreach u $unplaced {
    lassign $u name dir tPtr status
    set side ""
    if {$dir eq "input"}  { set side L }
    if {$dir eq "output"} { set side R }
    lassign [directNetCentroid $tPtr] cx cy cn
    if {$side eq ""} {
        # Use net centroid X to pick the closer die edge.
        if {$cn > 0 && abs($cx - $xR) < abs($cx - $xL)} {
            set side R
        } else {
            set side L
        }
    }
    set xEdge [expr {$side eq "L" ? $xL : $xR}]
    set related [bfsRelated $tPtr $BFS_MAX_HOPS $BFS_MAX_NET_FANOUT \
                            $BFS_MAX_VISITS ANCHOR]
    set ys         [list]
    set anchorList [list]
    if {[llength $related] > 0} {
        # Take the smallest-hop group (and 1 hop wider for robustness)
        set sorted [lsort -integer -index 1 $related]
        set minHop [lindex [lindex $sorted 0] 1]
        foreach r $sorted {
            lassign $r pn hop
            if {$hop > $minHop + 1} { break }
            lassign $ANCHOR($pn) aSide ay alyr ax
            # Only consider anchors on the SAME side (else the geographic anchor is far)
            if {$aSide ne $side} { continue }
            lappend ys $ay
            lappend anchorList "$pn@$hop"
        }
        if {[llength $ys] == 0} {
            # All related anchors were on the opposite side -> fall back to all hops same side
            foreach r $sorted {
                lassign $r pn hop
                lassign $ANCHOR($pn) aSide ay alyr ax
                if {$aSide eq $side} {
                    lappend ys $ay
                    lappend anchorList "$pn@$hop*"
                    if {[llength $ys] >= 4} { break }
                }
            }
        }
    }
    if {[llength $ys] == 0 && $cn > 0} {
        # BFS gave nothing (typical for clk/reset spine). Use direct net centroid.
        lappend ys $cy
        lappend anchorList "netCentroid(N=$cn,fanout-uncapped)"
        if {$side eq "L"} { incr fallbackInputs } else { incr fallbackOutputs }
    }
    if {[llength $ys] == 0} {
        # Net has no instTerms either: park at die-center Y.
        lappend ys [expr {($yB+$yT)/2.0}]
        lappend anchorList "die-center(no-net-loads)"
        if {$side eq "L"} { incr fallbackInputs } else { incr fallbackOutputs }
    }
    # Target Y = median
    set ys [lsort -real $ys]
    set targetY [lindex $ys [expr {[llength $ys]/2}]]
    # Search nearest free slot within +/-MAX_DELTA tracks across all layers
    set i0 [yToIdx $targetY]
    set chosenIdx -1
    set chosenLyr ""
    for {set d 0} {$d <= $MAX_DELTA && $chosenIdx < 0} {incr d} {
        foreach off [list $d [expr {-$d}]] {
            if {$d == 0 && $off < 0} { continue }
            set i [expr {$i0 + $off}]
            if {$i < 0 || $i > $BASE_NUM-1} { continue }
            foreach L $IO_LAYER_NAMES {
                if {![info exists USED("$side|$i|$L")]} {
                    set chosenIdx $i
                    set chosenLyr $L
                    break
                }
            }
            if {$chosenIdx >= 0} { break }
        }
    }
    # Overflow widen if no slot within 2um
    if {$chosenIdx < 0} {
        for {set d [expr {$MAX_DELTA+1}]} {$d <= $BASE_NUM && $chosenIdx < 0} {incr d} {
            foreach off [list $d [expr {-$d}]] {
                set i [expr {$i0 + $off}]
                if {$i < 0 || $i > $BASE_NUM-1} { continue }
                foreach L $IO_LAYER_NAMES {
                    if {![info exists USED("$side|$i|$L")]} {
                        set chosenIdx $i
                        set chosenLyr $L
                        break
                    }
                }
                if {$chosenIdx >= 0} { break }
            }
        }
    }
    set USED("$side|$chosenIdx|$chosenLyr") $name
    set yFinal [idxToY $chosenIdx]
    if {$yFinal < $yB} { set yFinal $yB }
    if {$yFinal > $yT} { set yFinal $yT }
    set dev [expr {abs($yFinal - $targetY)}]
    lappend results [list $name $side $yFinal $targetY $dev $chosenLyr \
                          [join $anchorList ","]]
}

# --------------------- 5) summary -------------------------------------
set okIn  0; set okOut 0
set overIn 0; set overOut 0
foreach r $results {
    lassign $r name side yF tY dv lyr note
    if {$yF eq ""} { continue }
    if {$side eq "L"} {
        if {$dv <= $MAX_RELATED_DIST} { incr okIn } else { incr overIn }
    } else {
        if {$dv <= $MAX_RELATED_DIST} { incr okOut } else { incr overOut }
    }
}
puts "INFO: placed remaining: left ok=$okIn over2um=$overIn ; right ok=$okOut over2um=$overOut"
puts "INFO: net-centroid fallback used: inputs=$fallbackInputs outputs=$fallbackOutputs (all such ports were still placed)"

# --------------------- 6) emit + apply --------------------------------
set fh [open $OUT_TCL w]
puts $fh "###############################################################################"
puts $fh "# Auto-generated by place_remaining_ports.tcl (phase 2)"
puts $fh "# Placed by netlist-association BFS. Max +/-${MAX_RELATED_DIST}um from anchor."
puts $fh "###############################################################################"
puts $fh ""
foreach r $results {
    lassign $r name side yF tY dv lyr note
    if {$yF eq ""} {
        puts $fh "# SKIP $name reason=$note"
        continue
    }
    set xEdge [expr {$side eq "L" ? $xL : $xR}]
    puts $fh [format "editPin -pin %s -fixedPin 1 -snap TRACK -layer %s -assign \{%.4f %.4f\}  ;# anchors=%s targetY=%.4f dev=%.3f" \
              $name $lyr $xEdge $yF $note $tY $dv]
}
close $fh
puts "INFO: wrote $OUT_TCL"

# Report
set fr [open $OUT_RPT w]
puts $fr "# place_remaining_ports report"
puts $fr "# IO box: ($xL,$yB)-($xR,$yT)   layers=[join $IO_LAYER_NAMES ,]  step=$BASE_STEP"
puts $fr "# anchors used = $numAnchored ; unplaced examined = [llength $unplaced]"
puts $fr "# left:  ok=$okIn  >${MAX_RELATED_DIST}um=$overIn   fallback=netCentroid:$fallbackInputs"
puts $fr "# right: ok=$okOut >${MAX_RELATED_DIST}um=$overOut  fallback=netCentroid:$fallbackOutputs"
puts $fr ""
puts $fr "# side  port                                yFinal  targetY  dev   layer  anchors / note"
foreach r $results {
    lassign $r name side yF tY dv lyr note
    if {$yF eq ""} {
        puts $fr [format "?     %-35s   -        -        -    -     %s" $name $note]
    } else {
        puts $fr [format "%-1s     %-35s %8.4f %8.4f %5.3f  %-3s   %s" \
                  $side $name $yF $tY $dv $lyr $note]
    }
}
close $fr
puts "INFO: wrote $OUT_RPT"

source $OUT_TCL
catch { snapAllBlockPinsToTracks }
puts "place_remaining_ports.tcl DONE"
