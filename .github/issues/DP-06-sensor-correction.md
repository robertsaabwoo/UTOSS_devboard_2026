---
id: DP-06
title: "RTL: sensor correction — dark-frame subtraction, bad-pixel map, optional flat-field"
labels: [rtl, P2, "area:datapath", "size:M"]
depends_on: [DP-04, MEM-02, D-01]
---

## What

Per-sample radiometric correction before compression: dark-frame subtraction, a
bad-pixel map, and optionally flat-field (gain) correction.

## Why P2, and why it is still on the list

`rtl/RTL_PLAN.md` §4 calls it "optional but usually needed". The sensor decides:
some sensors do this internally, some do not, and for a hyperspectral instrument
the dark current varies strongly with band and temperature.

It is P2 because the payload produces a usable compressed cube without it, and
because correction can be done on the ground **provided the calibration frames are
downlinked**. But there is a compression argument for doing it on board: CCSDS 123
predicts each sample from its neighbours, so a fixed-pattern offset that varies
per pixel is noise to the predictor and costs compression ratio directly. Removing
it on board can pay for itself in downlink volume.

**Settle that trade-off before building this.** Measure it: run a representative
cube through the `V-01` software model with and without correction and compare the
compressed sizes. If the gain is small, this stays P2 forever and the calibration
frames go down with the data instead.

## Interface

```verilog
module sensor_correct #(
    parameter integer SAMPLE_W = 16,
    parameter integer COORD_W  = 16,
    parameter integer GAIN_W   = 16,
    parameter integer GAIN_FRAC = 12,     // fixed-point fraction bits
    parameter         EN_DARK  = 1,
    parameter         EN_BADPX = 1,
    parameter         EN_FLAT  = 0        // costs a multiplier per sample
) (
    input  wire                  clk_sys,
    input  wire                  rst_sys_n,

    // Sample stream in (from DP-05)
    input  wire [SAMPLE_W-1:0]   s_tdata,
    input  wire [COORD_W-1:0]    s_x,
    input  wire [COORD_W-1:0]    s_y,
    input  wire [COORD_W-1:0]    s_band,
    input  wire                  s_tvalid,
    input  wire                  s_tlast,
    output wire                  s_tready,

    // Calibration fetch -- a read port on the memory arbiter (MEM-02), because
    // a full dark frame does not fit in EBR. See requirement 2.
    output wire [31:0]           cal_addr,
    output wire                  cal_req,
    input  wire                  cal_ack,
    input  wire [SAMPLE_W-1:0]   cal_dark,
    input  wire [GAIN_W-1:0]     cal_gain,
    input  wire                  cal_bad,

    // Corrected stream out
    output wire [SAMPLE_W-1:0]   o_tdata,
    output wire [COORD_W-1:0]    o_x,
    output wire [COORD_W-1:0]    o_y,
    output wire [COORD_W-1:0]    o_band,
    output wire                  o_tvalid,
    output wire                  o_tlast,
    input  wire                  o_tready,

    // Telemetry
    output wire [31:0]           bad_px_count,       // saturating
    output wire [31:0]           clamp_count,        // saturating
    output wire [15:0]           err_cal_timeout
);
```

## Behaviour requirements

1. **Underflow must clamp, not wrap.** `sample - dark` can go negative on a dark
   pixel. Clamping to zero loses information about the noise floor; wrapping produces
   a bright pixel where there was a dark one, which the predictor then has to encode
   expensively *and* which looks like a real signal on the ground. Clamp, count it
   (`clamp_count`), and say so in the header. A high clamp count is itself a useful
   diagnostic that the dark frame is stale.
2. **Where the calibration data lives is the main design decision.** A full dark
   frame at `width x bands x SAMPLE_W` will not fit in the 45F's EBR for any
   realistic geometry, so it comes from DDR3 — which makes this module a client of the
   `MEM-02` arbiter, competing with the camera write port and the compressor. Compute
   the required calibration read bandwidth (one read per sample, at the full sample
   rate) and check it against the arbiter budget **before** writing RTL. If it does
   not fit, the alternatives are a per-band scalar dark value held in EBR instead of a
   per-pixel frame, or correction on the ground. Both are legitimate; pick one with
   the number in hand.
3. **Bad-pixel replacement policy must be stated and must be one thing.** Nearest
   valid neighbour in the same band is the usual choice. Whatever it is, the ground
   team needs to know, because a replaced pixel is synthetic data and should not be
   treated as a measurement. Also pass the bad-pixel map down with the product, or
   mark replaced pixels, so this is recoverable.
4. **Flat-field costs a multiplier per sample.** At `EN_FLAT=1` this maps to a
   `MULT18X18D`. Budget it against `dsp_mult_18x18` in `rtl/ecp5_target.yaml` and
   against `CMP-01`, which wants the DSPs for the weight-update chain. The predictor
   has first claim.
5. **A calibration fetch timeout must not stall the pipeline forever.** On timeout,
   pass the sample through uncorrected, increment `err_cal_timeout`, and keep going. A
   correction block that deadlocks is strictly worse than no correction block.
6. Coordinates pass through unchanged. Latency through the module is fixed and
   documented, since `MEM-03` downstream may rely on it.
7. Correction must be **bypassable at run time** from the CSR, not just at compile
   time. A capture with a suspect calibration frame is better taken uncorrected than
   not taken.

## Resource budget

`EN_DARK + EN_BADPX`: under 300 LUTs. Adding `EN_FLAT`: one DSP plus ~100 LUTs.
Set `synth.budget` from a measured run, and check the DSP count explicitly.

## Acceptance criteria

- Reference model in the bench applying the same correction in Python; compare every
  output sample bit-exactly, across random calibration data.
- **Underflow**: samples below their dark value — output clamps to zero,
  `clamp_count` is exact, no wraparound. Assert the exact count.
- **Bad pixel**: every bad pixel in the map is replaced by the documented policy,
  `bad_px_count` is exact, and a bad pixel at the start and end of a line (where the
  neighbour policy has fewer choices) is handled.
- **Saturation at the top of the range** with flat-field gain > 1: clamps to the
  maximum, counted.
- **Calibration fetch timeout**: sample passes through uncorrected,
  `err_cal_timeout` increments, the pipeline keeps flowing. Assert no deadlock.
- **Run-time bypass**: output is bit-identical to the input, including coordinates.
- Backpressure and gaps on both interfaces produce bit-identical output to the
  gapless case; `check_stream_protocol` on both.
- A measurement, attached to the pull request, of the compression-ratio gain from
  on-board correction (requirement in the "why" section above) — the number that
  justifies this module existing in the FPGA at all.

## References

- `rtl/RTL_PLAN.md` §4
- `rtl/ecp5_target.yaml` (`dsp_mult_18x18`, `block_ram_blocks`)
- `MEM-02` (arbiter port budget), `V-01` (software model for the ratio measurement)
