`timescale 1ns / 1ps
`default_nettype none

// example_fifo -- a synchronous FIFO, written as the worked example of this
// repository's RTL conventions. Demo and teaching material; NOT flight RTL.
//
// It is deliberately simpler than the real thing. Issue I-01 asks for
// rtl/fpga/common/fifo_sync.v with sticky overflow/underflow flags and a
// high-water mark feeding the CSR telemetry, because on a payload that images
// for one minute a day an unreported dropped sample is worse than a crash.
// None of that is here. Do not copy this file into rtl/fpga/common/ and call
// I-01 done -- read the issue.
//
// What it does demonstrate, and what every module in rtl/fpga/ must also do
// (full list in rtl/README.md):
//
//   * `default_nettype none at the top, `default_nettype wire at the bottom,
//     so a typo'd signal name is a compile error instead of a silent new wire
//   * every width parameterized; no bare literal for a bus width
//   * derived widths via $clog2 in a localparam, never a second parameter
//     somebody has to keep in sync
//   * sized localparam constants (CNT_ONE, MAX_LEVEL) rather than bare
//     integers in expressions, so verilator -Wall cannot find an implicit
//     width change to complain about
//   * active-low reset, asynchronously asserted, synchronously released
//   * non-blocking assignment in clocked blocks only; no latches anywhere
//   * a non-power-of-two DEPTH actually works -- see the pointer wrap below
//
// DEPTH must be >= 2. WIDTH must be >= 1.
//
// MEMORY INFERENCE, which is the one thing worth studying here: rd_data is an
// asynchronous read of `mem`, so yosys infers distributed LUT RAM. That is the
// right choice for the small FIFOs this example is swept at, and the WRONG
// choice at, say, DEPTH=1024 x WIDTH=32 -- 32 kbit in LUTs costs roughly a
// hundred times what the same buffer costs in one EBR. The real fifo_sync has
// to infer EBR when it is large, and `tools/dev synth` is how you check which
// one you got. A 2 kB buffer that quietly became 16000 LUTs is a classic way
// to run out of an FPGA.
module example_fifo #(
    parameter integer WIDTH = 8,
    parameter integer DEPTH = 16
) (
    input  wire                        clk,
    input  wire                        rst_n,

    // Write port. Writing while full is ignored, not queued -- see below.
    input  wire                        wr_en,
    input  wire [WIDTH-1:0]            wr_data,
    output wire                        full,

    // Read port. rd_data continuously presents the oldest entry (first word
    // fall through); rd_en pops it. When empty, rd_data holds whatever was
    // last at that address -- it is NOT defined, and `empty` is the only
    // signal a consumer may believe.
    input  wire                        rd_en,
    output wire [WIDTH-1:0]            rd_data,
    output wire                        empty,

    // Current occupancy, 0..DEPTH inclusive -- hence DEPTH+1 distinct values.
    output wire [$clog2(DEPTH+1)-1:0]  level
);

  // $clog2(DEPTH) would be 0 at DEPTH==1, which is not a legal vector width.
  localparam integer ADDR_W = (DEPTH > 1) ? $clog2(DEPTH) : 1;
  localparam integer CNT_W  = $clog2(DEPTH + 1);

  // Sized constants. Writing `count + 1'b1` or `count == DEPTH` instead would
  // mix widths and verilator -Wall would reject it -- correctly, because that
  // is the same construct that silently truncates a pixel address elsewhere.
  localparam [CNT_W-1:0]  CNT_ONE   = 1;
  localparam [ADDR_W-1:0] ADDR_ONE  = 1;

  // Narrowing an integer parameter to a vector needs an explicit part-select.
  // Writing `localparam [CNT_W-1:0] MAX_LEVEL = DEPTH;` instead looks obviously
  // fine and verilator rejects it (WIDTHTRUNC): DEPTH is 32 bits and the target
  // is CNT_W, so the truncation is implicit. It is harmless here and it is the
  // identical construct that silently drops the top bits of a cube address
  // elsewhere, which is why the linter does not let either one through. Go via
  // a sized intermediate and say what is being kept.
  localparam [31:0]       DEPTH_32   = DEPTH;
  localparam [31:0]       LAST_32    = DEPTH - 1;
  localparam [CNT_W-1:0]  MAX_LEVEL  = DEPTH_32[CNT_W-1:0];
  localparam [ADDR_W-1:0] LAST_ADDR  = LAST_32[ADDR_W-1:0];

  reg [WIDTH-1:0]  mem [0:DEPTH-1];
  reg [ADDR_W-1:0] wr_ptr;
  reg [ADDR_W-1:0] rd_ptr;
  reg [CNT_W-1:0]  count;

  assign full    = (count == MAX_LEVEL);
  assign empty   = (count == {CNT_W{1'b0}});
  assign level   = count;
  assign rd_data = mem[rd_ptr];

  // Guarding both with full/empty is what makes an overflowing write harmless
  // instead of corrupting an entry that was already queued. A FIFO that
  // silently overwrites under pressure produces data loss with no symptom,
  // which is the failure this repo's telemetry requirements exist to prevent.
  wire do_wr = wr_en && !full;
  wire do_rd = rd_en && !empty;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= {ADDR_W{1'b0}};
    end else if (do_wr) begin
      // Compare-and-reset rather than a free-running counter: a counter that
      // relies on natural binary wrap only works when DEPTH is a power of two,
      // and would skip addresses for every other DEPTH. The `narrow_odd`
      // parameter set in bench.yaml uses DEPTH=7 to keep this honest.
      wr_ptr <= (wr_ptr == LAST_ADDR) ? {ADDR_W{1'b0}} : wr_ptr + ADDR_ONE;
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_ptr <= {ADDR_W{1'b0}};
    end else if (do_rd) begin
      rd_ptr <= (rd_ptr == LAST_ADDR) ? {ADDR_W{1'b0}} : rd_ptr + ADDR_ONE;
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      count <= {CNT_W{1'b0}};
    end else if (do_wr && !do_rd) begin
      count <= count + CNT_ONE;
    end else if (do_rd && !do_wr) begin
      count <= count - CNT_ONE;
    end
    // Simultaneous read and write leaves the level unchanged. This arm is the
    // off-by-one that FIFO implementations get wrong, and it is wrong in a way
    // that only shows up at the extremes -- which is why the bench exercises a
    // concurrent read/write at every occupancy from 0 to DEPTH rather than
    // trusting a random test to wander there.
  end

  always @(posedge clk) begin
    if (do_wr) begin
      mem[wr_ptr] <= wr_data;
    end
  end

endmodule

`default_nettype wire
