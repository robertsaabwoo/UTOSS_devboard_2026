`timescale 1ns/1ps

// Placeholder write-strobe register with a busy/ack handshake -- stands in
// for a memory-mapped register block sitting between FPGA fabric and a
// CPU/memory-facing bus. Proves the cocotb CI gate before real RTL exists.
module reg_handshake #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             wr_en,
    input  wire [WIDTH-1:0] data_in,
    output reg  [WIDTH-1:0] data_out,
    output reg              busy,
    output reg              ack
);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      data_out <= {WIDTH{1'b0}};
      busy     <= 1'b0;
      ack      <= 1'b0;
    end else begin
      ack <= 1'b0;  // single-cycle pulse
      if (wr_en && !busy) begin
        data_out <= data_in;
        busy     <= 1'b1;
      end else if (busy) begin
        busy <= 1'b0;
        ack  <= 1'b1;
      end
    end
  end

endmodule
