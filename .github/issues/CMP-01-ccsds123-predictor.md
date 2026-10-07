---
id: CMP-01
title: "RTL: CCSDS 123.0-B adaptive predictor — the core IP of this payload"
labels: [rtl, P0, "area:compression", "size:XL"]
depends_on: [V-01, D-03, MEM-03, MEM-02]
---

## What

The CCSDS 123.0-B adaptive predictor: local spatial and spectral neighbourhood
fetch, the weight-update MAC chain, prediction, and the mapped prediction residual.

## Why this is the most important issue in the repository

From `rtl/RTL_PLAN.md` §6: *"this is where the actual IP value is"* and
*"item 6 is the only part nobody else has already written."* Everything else in
this design is integration of known pieces. This is the part that makes the payload
worth building, and it is what cuts the downlink volume for a 20 MB/s instrument on
a satellite with a very limited downlink.

It is also the hardest to get right, because "almost correct" is not a thing a
compressor can be. A predictor that is one weight-update off from the standard
produces a bitstream that a conforming decompressor cannot decode — and the error
appears as garbage from the first sample where the weights diverge, not as slight
degradation.

## Start with the software model

**`V-01` is a hard prerequisite.** Do not write RTL for this before the golden
software model exists and has been checked against the standard's test vectors.
`rtl/RTL_PLAN.md` names the bit-exact comparison against a software CCSDS 123
implementation as *"the most valuable test in the project by a wide margin"*, and
this is why: without it, there is no way to know the RTL is right, and no way to
localise the divergence when it is not.

## Deliverables

- `rtl/fpga/ccsds123_neighbourhood.v` — the spatial/spectral neighbour fetch and
  its on-chip line/band buffering
- `rtl/fpga/ccsds123_weights.v` — the weight vector store and update chain
- `rtl/fpga/ccsds123_predict.v` — local sum, local difference, predicted sample,
  mapped residual
- `rtl/fpga/ccsds123_top.v` — the three together, with the `MEM-02` port
- A bench per module, plus the full bit-exact comparison against `V-01`
- `docs/CCSDS123_CONFIG.md` — exactly which configuration of the standard is
  implemented, and which optional features are not

## Decide and write down, before any RTL

CCSDS 123.0-B has a large configuration space, and the RTL only implements one
point in it. Fix the point first:

- [ ] **123.0-B-1 or -B-2?** B-2 adds near-lossless. Lossless-only is a smaller
      build; near-lossless is a much better compression ratio at a science cost that
      is the instrument team's call, not ours. Ask them, and record the answer.
- [ ] **Number of prediction bands *P***. This directly sets the weight vector
      length, the number of MACs per sample, and the spectral working set. It is the
      main area/ratio lever in the whole design.
- [ ] **Full or reduced prediction mode.** Reduced drops the spatial component —
      much smaller, lower ratio.
- [ ] **Local sum type** (neighbour-oriented or column-oriented). Column-oriented
      needs less line buffering, which matters a great deal on a part with ~237 KB of
      EBR.
- [ ] **Weight resolution Ω, weight update scaling exponent**, and the initial
      weight values. All are bitstream-affecting: get one wrong and the output is
      undecodable.
- [ ] **Samples per clock.** One sample per cycle at 100 MHz is 100 MS/s, far above
      the ~20 MB/s requirement — so a multi-cycle-per-sample implementation is almost
      certainly the right trade, and it saves a great deal of area. Work out the real
      required sample rate from `D-01`'s sensor and `D-03`'s geometry, then pick the
      smallest parallelism that meets it with margin. This decision alone can be the
      difference between fitting on the part and not.

## Interface sketch

```verilog
module ccsds123_top #(
    parameter integer SAMPLE_W   = 16,
    parameter integer COORD_W    = 16,
    parameter integer P_BANDS    = 3,     // prediction bands
    parameter integer OMEGA      = 13,    // weight resolution
    parameter integer REG_SIZE   = 32,    // accumulator/register width
    parameter integer MAX_WIDTH  = 2048,
    parameter integer SAMPLES_PER_CYCLE = 1
) (
    input  wire                  clk_sys,
    input  wire                  rst_sys_n,

    // Configuration from the CSR, latched at capture start
    input  wire [COORD_W-1:0]    cfg_width,
    input  wire [COORD_W-1:0]    cfg_bands,
    input  wire                  capture_start,

    // Sample stream in, with coordinates (from DP-05 or DP-06)
    input  wire [SAMPLE_W-1:0]   s_tdata,
    input  wire [COORD_W-1:0]    s_x,
    input  wire [COORD_W-1:0]    s_y,
    input  wire [COORD_W-1:0]    s_band,
    input  wire                  s_tvalid,
    input  wire                  s_tlast,
    output wire                  s_tready,

    // Mapped prediction residual out, to CMP-02
    output wire [SAMPLE_W:0]     r_tdata,      // one bit wider than the sample
    output wire                  r_tvalid,
    output wire                  r_tlast,
    input  wire                  r_tready,
    output wire [COORD_W-1:0]    r_band,       // CMP-02 needs it per-band

    // Working-set port on the MEM-02 arbiter (see requirement 3)
    output wire [31:0]           ws_addr,
    output wire                  ws_req,
    output wire                  ws_write,
    input  wire                  ws_ack,
    output wire [127:0]          ws_wdata,
    input  wire [127:0]          ws_rdata,

    output wire [31:0]           samples_done,
    output wire [15:0]           err_ws_timeout
);
```

## Behaviour requirements

1. **Bit-exactness with `V-01` is the requirement.** Not "close", not "visually
   identical". Every mapped residual, for every sample, for every tested cube and
   configuration.
2. **Edge cases are where conformance lives.** The first sample of a cube has no
   neighbours; the first line has no north; the first column has no west; the last
   column has no north-east; band 0 has no spectral predecessor; bands below *P* have
   fewer than *P* predecessors. The standard specifies exactly what to do in each
   case, and these are the cases an implementation gets wrong while passing on the
   cube interior. Enumerate them in the bench explicitly.
3. **The weight-update chain maps to DSP blocks** (`MULT18X18D`). Count them against
   `dsp_mult_18x18` in `rtl/ecp5_target.yaml`: *P* + 3 multiplies per sample for full
   prediction. At `P=3` that is 6 per sample per cycle of parallelism — and the 45F has
   72 in total. This is the constraint that decides `SAMPLES_PER_CYCLE`.
4. **The on-chip working set is the other hard constraint.** The predictor needs a
   line buffer across bands (`rtl/RTL_PLAN.md` "Risks": *"~126 KB of BRAM is thin for
   a predictor that needs a line buffer across bands"* — the 45F roughly doubles that
   but it is still the binding limit). Compute the requirement exactly:
   `cfg_width x P_BANDS x SAMPLE_W` bits for the spectral neighbours, plus the
   spatial line buffer. If it does not fit in EBR, part of it goes to DDR through
   `ws_*` — and then the predictor's inner loop has DDR latency in it, which is
   precisely what `D-03` was about. **Do this arithmetic before writing RTL**; the
   answer determines the architecture, and the maximum swath width the payload can
   support.
5. **Fixed-point arithmetic must match the standard exactly**, including rounding
   and clamping at every step. A rounding difference is a bitstream difference. Do not
   "simplify" an expression from the standard without proving equivalence over the full
   input range.
6. **Working-set timeout must not deadlock.** On `ws_*` timeout, increment
   `err_ws_timeout` and enter a defined failed state that the CSR reports. Do not
   continue with stale weights — that produces an undecodable bitstream that looks like
   a successful capture, which is strictly worse than an aborted one.
7. `default:` arm on every FSM; this is a TMR candidate in `C-05`.
8. Backpressure must be handled without affecting the output: a stalled `r_tready`
   must not perturb the weight state.

## Resource budget

`rtl/RTL_PLAN.md` estimates 5–10k LUTs for CCSDS 123 **plus** the Rice coder,
depending on parallelism. For this module alone, budget 4000–7000 LUTs, 10–20 EBRs
and 6–12 DSPs at `P=3, SAMPLES_PER_CYCLE=1`, and **set the budget from the first
measured run, then defend it**. This is the block most likely to not fit, and it is
the reason `D-02` moved the design to the 45F.

Report utilization in the pull request with the ceiling from
`rtl/ecp5_target.yaml` alongside it.

## Acceptance criteria

- **Bit-exact against `V-01`** on: a synthetic gradient cube, a synthetic noise
  cube, a real hyperspectral cube (AVIRIS or similar public data), and at minimum
  cubes with `bands = 1`, `bands = P`, `bands = P+1`, `width = 1`, `lines = 1`.
- Every edge case in requirement 2 has a named test.
- Bit-exact across at least three configurations (different *P*, Ω, full/reduced).
- Backpressure and gaps: output bit-identical to the gapless run. Assert this
  explicitly — a predictor whose weight state depends on stall timing is broken in a
  way that only shows up in integration.
- Working-set timeout: `err_ws_timeout` increments, defined failed state, no
  deadlock, and **no output is produced** after the failure.
- Reset mid-cube: the next capture starts from the standard's initial weight values,
  not from the previous cube's state. Assert on the first residual.
- Resource report within budget, with DSP and EBR counts explicitly checked against
  `rtl/ecp5_target.yaml`.
- `docs/CCSDS123_CONFIG.md` states every configuration choice, so a ground
  decompressor can be configured to match.

## References

- CCSDS 123.0-B-2, *Low-Complexity Lossless and Near-Lossless Multispectral and
  Hyperspectral Image Compression* (and the Green Book CCSDS 120.2-G-2)
- `rtl/RTL_PLAN.md` §6, "Verification", "Risks"
- `V-01` (golden model — prerequisite), `D-03` (layout and working set)
- `rtl/ecp5_target.yaml` (`dsp_mult_18x18`, `block_ram_blocks`)
