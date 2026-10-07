---
id: DP-04
title: "RTL: frame framer and pixel unpacker (packed 10/12/14-bit to aligned samples)"
labels: [rtl, P0, "area:datapath", "size:M"]
depends_on: [DP-01, I-01]
---

## What

Turn the raw receiver stream into a clean, aligned sample stream with frame, line
and band coordinates attached: sync detection, line/frame/band counters, bit-depth
unpacking, and partial-word handling at line ends.

## Why it is its own module

Everything downstream — correction (`DP-06`), the cube address generator
(`MEM-03`), the predictor (`CMP-01`) — needs to know *where* a sample is in the
cube, not just its value. Deriving that in three places independently is how two of
them end up disagreeing about where a line starts.

Unpacking is separate from receiving for the same reason: `DP-01`, `DP-02` and
`DP-03` all produce a different raw stream, and only one of them will ever exist.
Everything from here on is interface-independent.

## Interface

```verilog
module frame_framer #(
    parameter integer IN_W        = 14,   // receiver bus width
    parameter integer SAMPLE_W    = 16,   // aligned output sample width
    parameter integer BIT_DEPTH   = 12,   // significant bits per sample
    parameter integer PACKING     = 0,    // 0 = one sample per bus word,
                                          // 1 = packed, see requirement 2
    parameter integer MAX_WIDTH   = 2048, // samples per line
    parameter integer MAX_BANDS   = 256
) (
    input  wire                     clk_px,
    input  wire                     rst_px_n,

    // Configured per capture, from the CSR. Must not change mid-frame.
    input  wire [15:0]              cfg_line_width,
    input  wire [15:0]              cfg_bands,
    input  wire [15:0]              cfg_lines,

    // In, from DP-01/02/03
    input  wire [IN_W-1:0]          in_tdata,
    input  wire                     in_tvalid,
    output wire                     in_tready,
    input  wire                     in_tlast,
    input  wire [1:0]               in_tuser,    // {frame_start, frame_end}

    // Out: one aligned sample per beat, with its coordinates
    output wire [SAMPLE_W-1:0]      s_tdata,
    output wire                     s_tvalid,
    input  wire                     s_tready,
    output wire                     s_tlast,     // last sample of the cube
    output wire [15:0]              s_x,         // sample within line
    output wire [15:0]              s_y,         // line within frame
    output wire [15:0]              s_band,

    // Telemetry, saturating, to the CSR
    output wire [15:0]              frames_done,
    output wire [15:0]              err_geometry,   // line/frame size mismatch
    output wire [15:0]              err_partial,    // leftover bits at line end
    output wire [15:0]              err_cfg_change  // config changed mid-frame
);
```

## Behaviour requirements

1. **Coordinates are emitted with the sample, not inferred downstream.** `s_x`,
   `s_y` and `s_band` are the single source of truth about cube position.
2. **Packed bit depths**: at `PACKING=1`, samples are packed back-to-back across
   bus words — e.g. 12-bit samples on a 14-bit bus, so sample boundaries do not
   align with word boundaries, and a sample spans two words two-thirds of the time.
   Handle 10, 12 and 14-bit packing against the configured `IN_W`. This is tedious
   and it is where the bugs are: an off-by-one in the shift register corrupts every
   sample after the first line, subtly enough to look like sensor noise.
3. **Partial word at line end**: when a line's bits do not fill a whole bus word,
   the leftover bits are discarded at the line boundary and **counted**
   (`err_partial`). They must not leak into the first sample of the next line. This
   is the single most likely bug in this module, and it produces a cube where every
   line after the first is shifted by a few bits.
4. **`BIT_DEPTH` sign/alignment is explicit.** Say in the header whether samples are
   LSB-aligned and zero-extended into `SAMPLE_W`, or MSB-aligned. CCSDS 123 cares
   (`CMP-01`), and the two conventions differ by a factor of 16 in pixel value.
5. **Geometry mismatch is an error.** If the frame does not contain
   `cfg_line_width x cfg_lines x cfg_bands` samples, increment `err_geometry` and
   mark the frame bad — do not emit a short cube that downstream will treat as
   complete. A truncated cube that compresses "successfully" is the worst outcome
   available here.
6. **Configuration must not change mid-frame.** Latch `cfg_*` at frame start; if a
   CSR write changes them mid-frame, increment `err_cfg_change` and use the latched
   values. Otherwise the first half of a cube has different dimensions from the
   second and nothing downstream can tell.
7. Band ordering follows the layout decided in `D-03`. If the sensor is a pushbroom
   (one spatial line, all bands per readout) the mapping from the receiver stream to
   `(x, y, band)` is fixed by the sensor geometry — document it in the header, since
   getting it wrong transposes the cube.
8. `s_tlast` marks the last sample of the whole cube, not of a line. Line ends are
   derivable from `s_x`.

## Resource budget

Expect 400–800 LUTs and 400 FFs, plus any line-boundary buffering. The unpacker
shift register is the bulk. Set `synth.budget` from a measured run.

## Acceptance criteria

Parameter sets: `BIT_DEPTH` 10/12/14, `PACKING` 0 and 1, `IN_W` 8/14.

- **Reference model in the bench**: a Python unpacker that produces the expected
  sample sequence from the raw byte stream. Compare every sample. A hand-written
  expected list for one geometry will not catch requirement 2 or 3.
- **Every (BIT_DEPTH, IN_W, PACKING) combination**: full cube in, every sample and
  every coordinate triple correct.
- **Partial word at line end**: at least one geometry where the line length in bits
  is deliberately not a multiple of `IN_W`. Assert that the first sample of line
  *n+1* is correct and that `err_partial` increments exactly once per line. This is
  the test for requirement 3 and it is the most important one here.
- **Short frame** from the receiver: `err_geometry` increments, the frame is marked
  bad, and the **next** frame is framed correctly — i.e. one bad frame does not
  desynchronize the rest of the capture.
- **Long frame**: extra samples are discarded, counted, next frame correct.
- **Config change mid-frame**: `err_cfg_change` increments, the latched geometry is
  used, output stays consistent.
- **Backpressure** on `s_tready` with randomized stalls, and gaps on `in_tvalid`:
  bit-identical output to the gapless case. A shift-register unpacker that loses
  alignment under backpressure is a common failure and this test is what finds it.
- `check_stream_protocol` on both interfaces throughout.

## References

- `rtl/RTL_PLAN.md` §2
- `D-03` (cube layout and band ordering)
- `io_specs/fpga.yaml` `open_items/dcmi-bus-parameters`
