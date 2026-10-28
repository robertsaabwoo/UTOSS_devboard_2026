---
id: CMP-03
title: "RTL: bit packer / stuffer — variable-length codewords to aligned words"
labels: [rtl, P0, "area:compression", "size:M"]
depends_on: [CMP-02]
---

## What

Pack the variable-length codewords from `CMP-02` into aligned words for storage and
framing, and flush the final partial word correctly at the end of a cube.

## Why it is a separate, deceptively tricky module

It looks like a shift register and it is the module most likely to be quietly wrong.
A packer that drops or duplicates one bit at a buffer boundary produces a bitstream
that decodes correctly for the first *N* kilobytes and then becomes garbage — and
since the error is a bit offset rather than a corrupted value, the decompressor does
not fail cleanly, it produces a plausible wrong image. Keeping it separate means it
gets its own exhaustive bench.

## Interface

```verilog
module bit_packer #(
    parameter integer IN_MAX_LEN = 64,     // longest codeword from CMP-02
    parameter integer OUT_W      = 128     // DDR/storage word width
) (
    input  wire                     clk_sys,
    input  wire                     rst_sys_n,

    // Codewords in, left-aligned with a bit length
    input  wire [IN_MAX_LEN-1:0]    cw_data,
    input  wire [$clog2(IN_MAX_LEN+1)-1:0] cw_len,
    input  wire                     cw_valid,
    input  wire                     cw_last,
    output wire                     cw_ready,

    // Flush: emit the partial word, zero-padded. See requirement 3.
    input  wire                     flush,
    output wire                     flush_done,

    // Aligned words out
    output wire [OUT_W-1:0]         w_tdata,
    output wire                     w_tvalid,
    output wire                     w_tlast,
    input  wire                     w_tready,

    // The exact bit count, which the framing in CMP-04 needs so the decoder
    // knows where the real data ends inside the padded final word.
    output wire [39:0]              total_bits,
    output wire [$clog2(OUT_W)-1:0] final_pad_bits,
    output wire [15:0]              err_len_range   // cw_len > IN_MAX_LEN or 0
);
```

## Behaviour requirements

1. **Bit order must be stated and must be consistent.** MSB-first within a codeword
   and MSB-first within the output word is the CCSDS convention. Write it in the module
   header and do not deviate — this is the single most common way two halves of a
   compression chain end up incompatible, and it is invisible until a decompressor
   tries.
2. **A codeword may span more than two output words** if `IN_MAX_LEN` approaches
   `OUT_W`. Handle the general case; do not assume a codeword straddles at most one
   boundary.
3. **Flush must zero-pad and report the padding.** The final partial word is padded,
   and `total_bits` plus `final_pad_bits` tell `CMP-04` where the real data ends. A
   decompressor that treats the padding as data produces extra garbage samples at the
   end of every cube — and because it is at the end, it is easy to dismiss as
   acceptable, which it is not.
4. **`flush` must be idempotent and safe when the buffer is empty**: `flush_done`
   asserts, no spurious word is emitted.
5. **`cw_len = 0` and `cw_len > IN_MAX_LEN` are errors**, counted in
   `err_len_range`, not silently packed. A zero-length codeword silently dropped is a
   lost sample.
6. **`total_bits` must be exact**, and must match `bits_out` from `CMP-02`. It is
   also the number `D-04`'s storage arithmetic uses, so an error here propagates into
   a hardware decision.
7. Throughput: must sustain one codeword per cycle at the worst-case length, or the
   limit must be documented and checked against the required sample rate. A packer
   that stalls the compressor is a packer that makes the whole chain miss its deadline.
8. Backpressure on `w_tready` must not lose or reorder bits.

## Resource budget

A shift buffer of `OUT_W + IN_MAX_LEN` bits plus control: expect under 400 LUTs and
~250 FFs at `OUT_W=128, IN_MAX_LEN=64`. The variable shifter is the bulk; a wide
barrel shifter is expensive on an ECP5, so check the mapped size and consider a
two-stage shift if it is large.

## Acceptance criteria

This module should be tested to a higher standard than most, because its failures
are silent.

- **Reference model** in Python packing the same codeword sequence. Compare the
  output **bit by bit**, not word by word — a word-level comparison can pass with a
  bit-reversed codeword.
- **Exhaustive short sequences**: every combination of two consecutive codeword
  lengths from 1 to `IN_MAX_LEN` (bounded as needed), confirming the boundary case at
  every possible bit offset within the output word. This is the test that catches the
  off-by-one, and nothing else reliably does.
- **Long random sequence**: at least 100 000 codewords of random length and content;
  bit-exact.
- **A codeword spanning three output words** (requirement 2), at several offsets.
- **Flush at every possible bit offset** within the output word, including offset 0
  (nothing to pad) and `OUT_W - 1`. Assert `final_pad_bits` is exact in every case.
- **Flush on an empty buffer**: `flush_done` asserts, no word emitted.
- `cw_len = 0` and `cw_len` out of range: `err_len_range` increments, nothing is
  packed.
- **`total_bits` exact** across every test, and equal to the sum of the input
  lengths.
- Backpressure and gaps: bit-identical output to the gapless run.
- **Round trip**: `CMP-02` output into this packer, then unpacked in Python and fed
  back through the software decoder in `V-01`, recovering the original samples. This is
  the end-to-end check that no bit was lost at an alignment boundary.

## References

- `rtl/RTL_PLAN.md` §6, §7
- `CMP-02` (`bits_out` must agree with `total_bits`), `CMP-04` (consumes
  `final_pad_bits`)
