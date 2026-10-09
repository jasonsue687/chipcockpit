# Wrapper: run phase 1 then phase 2.
# Edit the param blocks at the top of each phase script before sourcing.
source [file dirname [info script]]/phase1_place_anchor_ports.tcl
source [file dirname [info script]]/phase2_place_remaining_ports.tcl
