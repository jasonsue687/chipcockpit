// SIMULATED fixture — synthetic netlist for flow validation, NOT a real design.
// release: simrel_2026Q2
module sim_block (input clk, input rst_n, input a, input b, output reg y);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) y <= 1'b0;
    else        y <= a & b;
endmodule
