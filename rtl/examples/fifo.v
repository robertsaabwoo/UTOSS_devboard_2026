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

    localparam integer ADDR_W = $clog2(DEPTH);
    localparam integer COUNT_W = $clog2(DEPTH + 1);


    reg [ADDR_W-1:0] rd_ptr; // points to next read location
    reg [ADDR_W-1:0] wr_ptr; // points to next available location to write

    reg [WIDTH-1:0] fifo [0:DEPTH-1]; // fifo array each element is WIDTH size and there are DEPTH entries

    reg [COUNT_W-1:0] count;
    assign rd_data = empty ? {WIDTH{1'b0}} : fifo[rd_ptr];
    assign empty = (count == 0);
    assign full = (count == DEPTH);

    wire do_rd = (rd_en && !empty);
    wire do_wr = (wr_en && !full);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin 
            wr_ptr <= 0;
            rd_ptr <= 0;
            count <= 0;

        end else begin 
            
            if (do_wr) begin
                fifo[wr_ptr] <= wr_data;
                wr_ptr <= wr_ptr + 1'b1;  
            end

            if (do_rd) begin
                rd_ptr <= rd_ptr + 1'b1;
            end

            case ({do_wr, do_rd}) 
                2'b01: count <= count - 1; // only a read occured, decrement count
                2'b10: count <= count + 1; // only awrite occured, incr
                default: count <= count;
            endcase
        
     end 
    end

endmodule

`default_nettype wire
