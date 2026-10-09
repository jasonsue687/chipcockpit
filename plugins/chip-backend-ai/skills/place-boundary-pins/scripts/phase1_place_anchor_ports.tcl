###############################################################################
#  place_lv_ports.tcl
#
#  Snap top-level ports that directly connect to EXAMPLE_BUF_X4
#  pins inside u_example_block0 / u_example_block1 onto the die boundary, with the
#  port pin Y aligned to the cell pin Y:
#
#     * input  ports -> LEFT  edge  (X = die.xLo)
#     * output ports -> RIGHT edge  (X = die.xHi)
#     * IO pins spread across 3 layers (M4 + M6 + M8) to expand the
#       per-Y slot budget 3x.
#     * For each port: search nearest free (layer, Y-track) slot within
#       +/-MAX_PORT_DEV (default 1um) of the cell pin Y.
#
#  Output:
#     custom_place/lv_port_assign.tcl  - editPin commands actually run
#     custom_place/lv_port_assign.rpt  - per-port placement + deviation
#
#  Usage:   innovus> source custom_place/place_lv_ports.tcl
###############################################################################

# ------------------------------------------------------------------ params --
set DB_PATH        "./example_dbs/example_top.floorplan.enc.dat"  ;# EXAMPLE path only
set TOP_NAME       "example_top"

set TARGET_HIERS   [list u_example_block0 u_example_block1]
set TARGET_CELL    "EXAMPLE_BUF_X4"

# Three vertical-preferred metal layers used for IO pins. The script
# tries M4 first, then M6, then M8 for each port - this minimises the
# via stack to the cell pin layer.
set IO_LAYER_NAMES [list M4 M6 M8]

# Allowed deviation from cell-pin Y when searching for a free slot (um).
set MAX_PORT_DEV   1.0

set OUT_TCL        "custom_place/lv_port_assign.tcl"
set OUT_RPT        "custom_place/lv_port_assign.rpt"

# ----------------------------------------------------------------- restore --
set _need_restore 1
if {[catch {set _hc [dbHeadCell]} _]} {
    set _need_restore 1
} elseif {$_hc ne "" && $_hc ne "0x0" && [catch {dbGet top.name} _topName] == 0 \
          && $_topName ne "" && $_topName ne "0x0"} {
    puts "INFO: design '$_topName' already loaded, skipping restoreDesign"
    set _need_restore 0
}
if {$_need_restore} {
    puts "INFO: restoring $DB_PATH"
    restoreDesign $DB_PATH $TOP_NAME
}

# ---------------------------------------------------------- die / io edges --
set fBox  [dbGet top.fPlan.box]
set fFlat [concat {*}$fBox]
set xL [lindex $fFlat 0]
set yB [lindex $fFlat 1]
set xR [lindex $fFlat 2]
set yT [lindex $fFlat 3]
puts "INFO: IO box ( $xL , $yB ) - ( $xR , $yT )"

# ------------------------------ Y-track grid for each IO layer (dir=y) -----
# dir=y tracks give Y positions (horizontal track lines on the layer),
# which is what edge pin Y must snap to.
proc layerYTrack {layerName} {
    foreach tg [dbGet top.fPlan.tracks] {
        if {[dbGet $tg.dir] ne "y"} { continue }
        set onLyr 0
        foreach lp [dbGet $tg.layers] {
            if {[dbGet $lp.name] eq $layerName} { set onLyr 1; break }
        }
        if {!$onLyr} { continue }
        return [list [dbGet $tg.start] [dbGet $tg.step] [dbGet $tg.numTracks]]
    }
    return [list]
}

array set GRID {}
foreach Ln $IO_LAYER_NAMES {
    set g [layerYTrack $Ln]
    if {[llength $g] != 3} { error "Layer $Ln has no dir=y track group" }
    set GRID($Ln) $g
    lassign $g s p n
    puts [format "INFO: %s Y-track grid: start=%.4f step=%.4f num=%d last=%.4f" \
          $Ln $s $p $n [expr {$s+($n-1)*$p}]]
}

# Pick the finest pitch for the global search step (so the algorithm
# can address every layer's tracks). All M4/M6/M8 are 0.076 in this DB.
set BASE_STEP  [lindex $GRID([lindex $IO_LAYER_NAMES 0]) 1]
set BASE_START [lindex $GRID([lindex $IO_LAYER_NAMES 0]) 0]
set BASE_NUM   [lindex $GRID([lindex $IO_LAYER_NAMES 0]) 2]
set MAX_TRACK_DELTA [expr {int(floor($MAX_PORT_DEV/$BASE_STEP))}]
puts "INFO: base Y grid (from [lindex $IO_LAYER_NAMES 0]): step=$BASE_STEP num=$BASE_NUM"
puts "INFO: +/-${MAX_PORT_DEV}um -> +/-${MAX_TRACK_DELTA} tracks of ${BASE_STEP}um"
puts "INFO: total slots (layers x tracks) = [expr {[llength $IO_LAYER_NAMES]*$BASE_NUM}]"

# ----------------------------------------- 1) collect LV cells of interest --
set lvInstPtrs [list]
set matched [dbGet -p2 top.insts.cell.name $TARGET_CELL -e]
if {$matched eq "" || $matched eq "0x0"} { error "No $TARGET_CELL instances" }
foreach instPtr $matched {
    set nm [dbGet $instPtr.name]
    foreach hp $TARGET_HIERS {
        if {[string match "${hp}/*" $nm]} { lappend lvInstPtrs $instPtr; break }
    }
}
puts "INFO: $TARGET_CELL count under [join $TARGET_HIERS ,] = [llength $lvInstPtrs]"

# --------------------------------- 2) walk pins, find direct-port mappings --
array set desired {}
foreach instPtr $lvInstPtrs {
    set instName [dbGet $instPtr.name]
    foreach iTerm [dbGet $instPtr.instTerms] {
        set netPtr [dbGet $iTerm.net -e]
        if {$netPtr eq "" || $netPtr eq "0x0"} { continue }
        set topTerms [dbGet $netPtr.terms -e]
        if {$topTerms eq "" || $topTerms eq "0x0"} { continue }
        set dir     [dbGet $iTerm.cellTerm.direction]
        set pinName [dbGet $iTerm.cellTerm.name]
        set pt      [concat {*}[dbGet $iTerm.pt]]
        set yPin    [lindex $pt 1]
        foreach tPtr $topTerms {
            set portName [dbGet $tPtr.name]
            if {![info exists desired($portName)]} {
                set desired($portName) [list $dir $yPin $instName $pinName]
            }
        }
    }
}
puts "INFO: collected [array size desired] unique direct port<->LV-pin mappings"

# --------------------------------- 3) split by direction, sort by desired Y --
set leftWants  [list]
set rightWants [list]
foreach port [array names desired] {
    lassign $desired($port) dir y inst pin
    if {$dir eq "input"}  { lappend leftWants  [list $port $y $inst $pin] }
    if {$dir eq "output"} { lappend rightWants [list $port $y $inst $pin] }
}
set leftWants  [lsort -real -index 1 $leftWants]
set rightWants [lsort -real -index 1 $rightWants]
puts "INFO:   left  (inputs)  = [llength $leftWants]"
puts "INFO:   right (outputs) = [llength $rightWants]"

# ----------------------------- 4) per-side multi-layer slot assignment ----
# Slot = (trackIdx, layerName).  For each port, sorted by desired Y,
# walk outward from desired track and try the layers in order. First free
# slot wins. If none free within MAX_TRACK_DELTA, widen the search (with
# the deviation warning baked into the result).

proc placePorts {wants layers gridArrName maxDelta yLo yHi} {
    upvar $gridArrName GRID
    array set used {}
    set out [list]
    foreach w $wants {
        lassign $w port y inst pin
        # Snap y to the base grid (all layers share same step here).
        set L0 [lindex $layers 0]
        lassign $GRID($L0) s p n
        set i0 [expr {int(round(($y - $s)/$p))}]
        if {$i0 < 0}        { set i0 0 }
        if {$i0 > $n-1}     { set i0 [expr {$n-1}] }
        set chosenIdx -1
        set chosenLyr ""
        # 1) Search within +/-MAX_TRACK_DELTA budget
        for {set d 0} {$d <= $maxDelta && $chosenIdx < 0} {incr d} {
            foreach off [list $d [expr {-$d}]] {
                if {$d == 0 && $off < 0} { continue }
                set i [expr {$i0 + $off}]
                if {$i < 0 || $i > $n-1} { continue }
                foreach L $layers {
                    if {![info exists used($i,$L)]} {
                        set chosenIdx $i
                        set chosenLyr $L
                        break
                    }
                }
                if {$chosenIdx >= 0} { break }
            }
        }
        # 2) Overflow: widen until any slot found
        if {$chosenIdx < 0} {
            for {set d [expr {$maxDelta+1}]} {$d <= $n && $chosenIdx < 0} {incr d} {
                foreach off [list $d [expr {-$d}]] {
                    set i [expr {$i0 + $off}]
                    if {$i < 0 || $i > $n-1} { continue }
                    foreach L $layers {
                        if {![info exists used($i,$L)]} {
                            set chosenIdx $i
                            set chosenLyr $L
                            break
                        }
                    }
                    if {$chosenIdx >= 0} { break }
                }
            }
        }
        set used($chosenIdx,$chosenLyr) $port
        set yFinal [expr {$s + $chosenIdx*$p}]
        if {$yFinal < $yLo} { set yFinal $yLo }
        if {$yFinal > $yHi} { set yFinal $yHi }
        set dev [expr {abs($yFinal - $y)}]
        lappend out [list $port $yFinal $y $dev $chosenLyr $inst $pin]
    }
    return $out
}

set leftFinal  [placePorts $leftWants  $IO_LAYER_NAMES GRID $MAX_TRACK_DELTA $yB $yT]
set rightFinal [placePorts $rightWants $IO_LAYER_NAMES GRID $MAX_TRACK_DELTA $yB $yT]

# Stats + per-layer counts
proc statsFor {final maxDev layers} {
    set n     [llength $final]
    set over  0
    set sum   0.0
    set maxD  0.0
    array set perL {}
    foreach L $layers { set perL($L) 0 }
    foreach r $final {
        set d [lindex $r 3]
        set L [lindex $r 4]
        set sum [expr {$sum + $d}]
        if {$d > $maxD} { set maxD $d }
        if {$d > $maxDev} { incr over }
        incr perL($L)
    }
    set avg [expr {$n > 0 ? $sum/$n : 0.0}]
    set perStr ""
    foreach L $layers { append perStr "${L}=$perL($L) " }
    return [list $n $over $avg $maxD $perStr]
}
lassign [statsFor $leftFinal  $MAX_PORT_DEV $IO_LAYER_NAMES] lN lO lAvg lMx lPer
lassign [statsFor $rightFinal $MAX_PORT_DEV $IO_LAYER_NAMES] rN rO rAvg rMx rPer
puts [format "INFO:   left  total=%d  >%.1fum=%d  avgDev=%.3f  maxDev=%.3f  byLayer{%s}" \
       $lN $MAX_PORT_DEV $lO $lAvg $lMx $lPer]
puts [format "INFO:   right total=%d  >%.1fum=%d  avgDev=%.3f  maxDev=%.3f  byLayer{%s}" \
       $rN $MAX_PORT_DEV $rO $rAvg $rMx $rPer]

# ------------------------------------------ 5) emit + source assign script --
set fh [open $OUT_TCL w]
puts $fh "###############################################################################"
puts $fh "# Auto-generated by place_lv_ports.tcl"
puts $fh "# Inputs  -> Left  edge (xL=$xL)"
puts $fh "# Outputs -> Right edge (xR=$xR)"
puts $fh "# IO layers = [join $IO_LAYER_NAMES ,]   base pitch=$BASE_STEP um"
puts $fh "###############################################################################"
puts $fh ""

proc emit {fh xEdge entries} {
    foreach e $entries {
        lassign $e port y yOrig dev layer inst pin
        # `dbGet .name` already wraps bus names in braces; emit raw.
        puts $fh [format "editPin -pin %s -fixedPin 1 -snap TRACK -layer %s -assign \{%.4f %.4f\}  ;# %s/%s yOrig=%.4f dev=%.3f" \
                  $port $layer $xEdge $y $inst $pin $yOrig $dev]
    }
}

puts $fh "# ------- LEFT edge (inputs) -------"
emit $fh $xL $leftFinal
puts $fh ""
puts $fh "# ------- RIGHT edge (outputs) -------"
emit $fh $xR $rightFinal
close $fh
puts "INFO: wrote $OUT_TCL ([expr {[llength $leftFinal]+[llength $rightFinal]}] lines)"

# Per-port report
set fr [open $OUT_RPT w]
puts $fr "# place_lv_ports report"
puts $fr "# IO box: ($xL,$yB)-($xR,$yT)   layers=[join $IO_LAYER_NAMES ,]  step=$BASE_STEP um"
puts $fr "# LV insts under [join $TARGET_HIERS ,] : [llength $lvInstPtrs]"
puts $fr "# left  inputs : total=$lN  >${MAX_PORT_DEV}um=$lO  avg=[format %.3f $lAvg]  max=[format %.3f $lMx]  byLayer{$lPer}"
puts $fr "# right outputs: total=$rN  >${MAX_PORT_DEV}um=$rO  avg=[format %.3f $rAvg]  max=[format %.3f $rMx]  byLayer{$rPer}"
puts $fr ""
puts $fr "# side  port                                yFinal   yOrig    dev     layer instPath/pin"
foreach r $leftFinal {
    lassign $r port y yOrig dev L inst pin
    puts $fr [format "L     %-35s %8.4f %8.4f %7.4f  %-3s   %s/%s" $port $y $yOrig $dev $L $inst $pin]
}
foreach r $rightFinal {
    lassign $r port y yOrig dev L inst pin
    puts $fr [format "R     %-35s %8.4f %8.4f %7.4f  %-3s   %s/%s" $port $y $yOrig $dev $L $inst $pin]
}
close $fr
puts "INFO: wrote $OUT_RPT"

# Apply (comment out for report-only)
source $OUT_TCL
catch { snapAllBlockPinsToTracks }
puts "place_lv_ports.tcl DONE"
