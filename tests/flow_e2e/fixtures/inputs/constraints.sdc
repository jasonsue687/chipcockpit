# SIMULATED fixture — synthetic SDC for flow validation, NOT real constraints.
# release: simrel_2026Q2
create_clock -name clk -period 1.000 [get_ports clk]
set_input_delay  0.10 -clock clk [get_ports {a b}]
set_output_delay 0.10 -clock clk [get_ports y]
