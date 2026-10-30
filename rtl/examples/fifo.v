`timescale 1ns / 1ps
`default_nettype none

// fifo -- synchronous FIFO, one clock. EXERCISE: this module is empty; write it.
//
//   make sim   ARGS="--only fifo"                       # run the tests
//   make waves ARGS="--only fifo --param-set minimal"   # and get a waveform
//   make synth ARGS="--only fifo"                       # what it costs in LUTs/FFs
//
// Done when every run says `pass`. Instructions: rtl/examples/README.md.
//
// Spec (rtl_tests/examples/fifo/test_fifo.py checks exactly this):
//   * Holds up to DEPTH entries of WIDTH bits. DEPTH is a power of two, >= 2.
//   * Write: on a rising edge with wr_en=1 and full=0, wr_data is stored.
//     A write while full is ignored and must not disturb stored data.
//   * Read: rd_data shows the oldest entry whenever empty=0, BEFORE rd_en is
//     asserted (first-word fall-through: no read latency). rd_en means "I have
//     taken it": on a rising edge with rd_en=1 and empty=0 that entry is
//     removed and rd_data moves on to the next one. A read while empty is
//     ignored.
//   * Read and write in the same cycle both happen.
//   * Out of reset: empty=1, full=0.
//
// Repo conventions (rtl/README.md): active-low reset, asynchronous assert;
// non-blocking assignments in clocked blocks; widths from parameters, e.g.
// localparam integer ADDR_W = $clog2(DEPTH).
module fifo #(
    parameter integer WIDTH = 8,
    parameter integer DEPTH = 16
) (
    input  wire             clk,
    input  wire             rst_n,

    input  wire             wr_en,
    input  wire [WIDTH-1:0] wr_data,
    output wire             full,

    input  wire             rd_en,
    output wire [WIDTH-1:0] rd_data,
    output wire             empty
);

  // ---- PLACEHOLDER: delete from here to END PLACEHOLDER ----------------------
  // Ties the outputs off so the empty module lints and builds. Change the
  // outputs to `output reg` if you prefer to drive them from always blocks.
  assign full    = 1'b0;
  assign empty   = 1'b1;
  assign rd_data = {WIDTH{1'b0}};

  /* verilator lint_off UNUSEDSIGNAL */
  wire unused_placeholder = &{1'b0, clk, rst_n, wr_en, wr_data, rd_en};
  /* verilator lint_on UNUSEDSIGNAL */
  // ---- END PLACEHOLDER -------------------------------------------------------

endmodule

`default_nettype wire
