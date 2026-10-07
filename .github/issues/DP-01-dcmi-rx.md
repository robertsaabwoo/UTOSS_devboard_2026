---
id: DP-01
title: "RTL: parallel camera receiver (DCMI-style PCLK/HSYNC/VSYNC capture)"
labels: [rtl, P0, "area:datapath", "size:M"]
depends_on: [I-01, I-02]
---

## What

Capture the camera's source-synchronous parallel video bus into the FPGA and
present it as a stream in the `clk_px` domain. `DCMI_RX` in
`io_specs/fpga.yaml`.

## Status against D-01

This is the **parallel** path, which is what `io_specs/camera.yaml` and
`io_specs/fpga.yaml` currently describe. It is the cheapest of the three options
by a wide margin. `D-01` may replace it with `DP-02` (Camera Link) or `DP-03`
(GigE Vision) — but the bus parameters below are parameterized precisely so that
work done here is not wasted if the sensor changes within the parallel family, and
everything downstream of this module (`DP-04` onward) is independent of the choice.

Start it. Do not wait for `D-01`.

## Deliverables

- `rtl/fpga/dcmi_rx.v`
- `rtl_tests/common/utoss_tb/camera_model.py` — the synthetic camera driver
  (shared with `V-02`; coordinate so it is written once)
- A bench

## Interface

```verilog
module dcmi_rx #(
    // Every one of these is a camera property and UNCONFIRMED until D-01.
    // See io_specs/fpga.yaml open_items/dcmi-bus-parameters.
    parameter integer DATA_W       = 14,      // 8 / 10 / 12 / 14
    parameter         HSYNC_ACTIVE = 1'b1,
    parameter         VSYNC_ACTIVE = 1'b1,
    parameter         SAMPLE_RISING = 1'b1,   // which PCLK edge data is valid on
    parameter integer SYNC_STAGES  = 2
) (
    // Pixel-clock domain, sourced from the camera.
    input  wire                clk_px,
    input  wire                rst_px_n,

    // Pads
    input  wire                pclk_in,       // for reference/monitoring only
    input  wire                hsync_in,
    input  wire                vsync_in,
    input  wire [DATA_W-1:0]   data_in,

    input  wire                enable,        // from the capture FSM (INT-01)

    // Stream out, clk_px domain. rtl/README.md §5.
    output wire [DATA_W-1:0]   px_tdata,
    output wire                px_tvalid,
    input  wire                px_tready,
    output wire                px_tlast,      // end of line
    output wire [1:0]          px_tuser,      // {frame_start, frame_end}

    // Telemetry -- all saturating, all to the CSR
    output wire [15:0]         frame_count,
    output wire [15:0]         line_count,
    output wire [15:0]         err_short_line,
    output wire [15:0]         err_short_frame,
    output wire [15:0]         err_px_overrun, // px_tvalid while !px_tready
    output wire                no_pclk         // watchdog, see requirement 6
);
```

## Behaviour requirements

1. **`clk_px` is the camera's clock**, buffered into the fabric. Data is captured
   on the edge given by `SAMPLE_RISING`. PCLK must land on a clock-capable input pin
   in the same bank as the data — that is a constraint on `I-03`, and it is what
   makes setup/hold across the bus achievable at all. Note it in the module header
   so the constraint and the RTL cannot drift apart.
2. **Synchronize `hsync_in` and `vsync_in`** with `sync_2ff` (`I-01`) if they are
   not already synchronous to `clk_px`. Data lines are source-synchronous and must
   **not** be synchronized — that would destroy the timing relationship. State the
   distinction in the header; it is counter-intuitive and somebody will "fix" it.
3. **Polarity and edge are parameters, not assumptions.** All four properties in the
   parameter list are unknown until `D-01`. A receiver that hard-codes
   active-high HSYNC works perfectly against the model it was written with and not
   at all against the sensor that arrives.
4. **A short line is an error, not a shrug.** Count the pixels between HSYNC
   assertions; if it differs from the previous line, increment `err_short_line`.
   Likewise a frame with the wrong line count increments `err_short_frame`. The
   capture cannot be re-taken, so detecting a malformed frame *at the input* is
   worth a great deal more than discovering a misaligned cube on the ground.
5. **`px_tready` going low must be counted, and the behaviour must be defined.**
   The camera cannot be backpressured — it keeps clocking data out regardless. So
   either the downstream FIFO (`DP-05`) absorbs it or pixels are lost; there is no
   third option. Count it (`err_px_overrun`) and document which pixels are dropped
   (the newest). Silent loss here is a corrupted cube that looks fine.
6. **`no_pclk` watchdog**: if `clk_px` is not toggling, the design must say so
   rather than sit in an unnameable state. Implement the detector in `clk_sys` (a
   counter that expects `clk_px` activity) and feed it to `I-02` and the CSR. The
   camera is power-gated and may simply not be streaming.
7. `enable` gates capture at a **frame boundary**, never mid-frame. Starting a
   capture halfway through a frame yields a partial cube that will be silently
   treated as a whole one.
8. `px_tuser` marks frame start and end, so `DP-04` can frame without re-deriving
   it from the sync signals.

## Resource budget

Expect under 300 LUTs and 300 FFs. Set `synth.budget` from a measured run. If it
is much larger than that, something is being done in the pixel domain that belongs
downstream.

## Acceptance criteria

The camera model BFM must be able to misbehave on demand. Parameter sets: `DATA_W`
8/10/14, both polarities, both sampling edges.

- **Nominal frames**: N frames of W×H pixels through the model, every pixel
  arrives in order, `frame_count` and `line_count` correct.
- **Every polarity/edge combination** produces identical pixel data, driven from the
  parameter set. This is the test that proves requirement 3.
- **Short line**: model truncates one line — `err_short_line` increments, the
  receiver resynchronizes on the next HSYNC rather than losing frame alignment for
  the rest of the capture.
- **Short frame**: model truncates a frame — `err_short_frame` increments,
  resynchronizes on the next VSYNC.
- **Extra-long line**: one line with more pixels than the rest — counted, and
  alignment recovered.
- **Backpressure**: `px_tready` held low for a burst — `err_px_overrun` increments
  by exactly the number of pixels lost. The bench asserts the exact count, not just
  that it is non-zero; an overrun counter that is off by a factor of the bus width
  is worse than none.
- **No pixel clock**: model stops clocking — `no_pclk` asserts, nothing deadlocks,
  CSR still readable.
- **Clock stops mid-frame and restarts**: the receiver recovers at the next frame
  boundary and reports the broken frame.
- **`enable` deasserted mid-frame**: capture stops at the frame boundary, not
  immediately, and the partial frame is not emitted.
- `check_stream_protocol` running on `px_*` throughout every test.

## References

- `rtl/RTL_PLAN.md` §1 (plain parallel), §2
- `io_specs/fpga.yaml` (`DCMI_RX`, `open_items/dcmi-bus-parameters`,
  `open_items/bank-pin-assignment`), `io_specs/camera.yaml` (`DCMI_OUT`)
