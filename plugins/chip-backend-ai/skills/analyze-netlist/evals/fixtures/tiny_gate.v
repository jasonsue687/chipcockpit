// Tiny synthetic gate-level netlist for testing.
// Two flops + combinational logic + a 2-bit bus output.
// Library cell names follow a generic prefix (CKND2D1 = inverter, AN2D1 = AND).
module sub_xor (input A, input B, output Y);
  XOR2D1 u_xor (.A(A), .B(B), .Y(Y));
endmodule

module tiny_gate (
    input        clk,
    input        rstn,
    input        din_a,
    input        din_b,
    output [1:0] dout
);
  wire n1, n2, n3;

  // first stage: AND of inputs
  AN2D1 u_and1 (.A(din_a), .B(din_b), .Y(n1));
  // second stage: XOR via submodule
  sub_xor u_x   (.A(n1), .B(din_a), .Y(n2));
  // third stage: invert
  CKND2D1 u_inv (.A(n2), .Y(n3));

  // sequential elements driven by n3
  DFCND1 u_ff0 (.D(n3), .CK(clk), .CDN(rstn), .Q(dout[0]));
  DFCND1 u_ff1 (.D(dout[0]), .CK(clk), .CDN(rstn), .Q(dout[1]));
endmodule
