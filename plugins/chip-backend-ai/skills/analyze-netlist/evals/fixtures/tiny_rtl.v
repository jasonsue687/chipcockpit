// Tiny RTL fixture: behavioral counter to test the RTL fallback path.
module tiny_rtl (
    input        clk,
    input        rst_n,
    input        enable,
    output reg [3:0] count
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      count <= 4'b0;
    else if (enable)
      count <= count + 1'b1;
  end

  assign count = count; // self-loop noise to exercise behavioral detection
endmodule
