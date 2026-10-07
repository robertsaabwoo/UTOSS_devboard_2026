---
id: CMP-02
title: "RTL: CCSDS 121.0-B Rice / sample-adaptive entropy coder with code-option search"
labels: [rtl, P0, "area:compression", "size:L"]
depends_on: [CMP-01, V-01]
---

## What

The entropy coder behind the predictor: either CCSDS 121.0-B Rice / adaptive
entropy coding, or CCSDS 123's own sample-adaptive encoder. Plus the code-option
search that picks the best parameter per block.

## Decide which encoder first

`rtl/RTL_PLAN.md` §6 lists both options, and they are genuinely different builds:

- **CCSDS 123's sample-adaptive encoder** — specified in the same standard as
  `CMP-01`, adapts per-sample from running accumulators, no block buffering, no code
  search. Smaller, simpler, streams naturally.
- **CCSDS 121.0-B Rice coder** — block-adaptive: buffer *J* samples, try every code
  option, pick the shortest. Better ratio on some data, but needs a block buffer and
  *N* parallel length calculations.

Pick one, with a measured justification from `V-01` on representative data. Do not
build both. Record the choice and the measurement in `docs/ENTROPY_CODER.md`.

The sample-adaptive encoder is the smaller and better-integrated choice unless the
measurement says otherwise — it shares the standard, the configuration and the
conformance test vectors with `CMP-01`.

## Interface sketch (sample-adaptive variant)

```verilog
module ccsds_entropy_enc #(
    parameter integer RESIDUAL_W   = 17,   // SAMPLE_W + 1 from CMP-01
    parameter integer COORD_W      = 16,
    parameter integer MAX_BANDS    = 256,
    // Accumulator initialisation and rescaling counter, both bitstream-affecting.
    parameter integer ACC_INIT_CONST = 6,
    parameter integer RESCALE_CNT  = 6,
    parameter integer U_MAX        = 18    // unary length limit
) (
    input  wire                   clk_sys,
    input  wire                   rst_sys_n,
    input  wire                   capture_start,
    input  wire [COORD_W-1:0]     cfg_bands,

    // Mapped residuals in, from CMP-01
    input  wire [RESIDUAL_W-1:0]  r_tdata,
    input  wire [COORD_W-1:0]     r_band,
    input  wire                   r_tvalid,
    input  wire                   r_tlast,
    output wire                   r_tready,

    // Variable-length codeword out, to CMP-03
    output wire [63:0]            cw_data,     // left-aligned
    output wire [6:0]             cw_len,      // valid bits in cw_data
    output wire                   cw_valid,
    output wire                   cw_last,
    input  wire                   cw_ready,

    output wire [31:0]            bits_out,    // running output bit count
    output wire [15:0]            err_u_max    // see requirement 4
);
```

## Behaviour requirements

1. **Bit-exact against `V-01`.** The entropy coder is where a one-bit error makes
   the whole remaining bitstream undecodable, so there is no partial credit.
2. **Per-band accumulator state.** The sample-adaptive encoder keeps an accumulator
   and counter **per band**, not globally. At `MAX_BANDS=256` that is 256 accumulator
   pairs — size them, and decide EBR versus distributed registers with
   `tools/dev synth`. Getting the per-band indexing wrong produces output that is
   correct for band 0 and garbage after.
3. **Accumulator rescaling must happen at exactly the specified counter value.**
   Off by one and the bitstream diverges from that sample onward.
4. **The unary length limit `U_MAX` must be enforced exactly as specified**,
   including the escape encoding for residuals that exceed it. This is the path least
   likely to be exercised by typical data and most likely to be wrong — count how
   often it is taken (`err_u_max`) so the bench can confirm it was actually tested
   rather than assumed.
5. **Initial accumulator values come from the standard**, parameterized, and must be
   reset per capture — not carried over from the previous cube.
6. **Codeword output is variable length**, left-aligned in `cw_data` with `cw_len`
   valid bits. `CMP-03` does the packing. Do not pack here; two modules doing partial
   packing is how bit alignment gets lost.
7. **If the Rice variant is chosen instead**: the code-option search is *N* parallel
   length calculations over a *J*-sample block, and the area scales with *N*. Budget it
   explicitly, and include the block buffer in the EBR budget.
8. Backpressure on `cw_ready` must not perturb the accumulator state. Assert that the
   output is bit-identical with and without stalls.

## Resource budget

Sample-adaptive: expect 1000–2000 LUTs, plus EBR for the per-band accumulators.
Rice with a search over 16 options: add 1000–2000 LUTs for the parallel length
calculations and the block buffer. `rtl/RTL_PLAN.md` budgets 5–10k LUTs for
`CMP-01` + `CMP-02` together — this half should be the smaller one.

## Acceptance criteria

- **Bit-exact against `V-01`** on every cube and configuration used for `CMP-01`,
  comparing the complete output bitstream, not just lengths.
- Residual = 0 and residual = maximum for the sample width, repeatedly, at the start
  of a cube and mid-cube.
- **A cube constructed specifically to exceed `U_MAX`** on a meaningful fraction of
  samples; `err_u_max` increments and the escape encoding is bit-exact. Assert
  `err_u_max > 0` in that test, so a bench that never reaches the path cannot pass
  silently.
- Accumulator rescaling boundary: a cube long enough to rescale several times per
  band, bit-exact across every rescale.
- `bands = 1` and `bands = MAX_BANDS`: per-band state indexing correct at both
  extremes.
- Backpressure and gaps: output bitstream bit-identical to the gapless run.
- Reset mid-cube: accumulators return to their specified initial values; assert on
  the first codeword of the next capture.
- Output bit count matches the software model exactly, which is also the number
  `D-04` needs for its storage arithmetic.

## References

- CCSDS 121.0-B-3 (*Lossless Data Compression*) and CCSDS 123.0-B-2 §5
  (sample-adaptive entropy coder)
- `rtl/RTL_PLAN.md` §6
- `V-01` (golden model — prerequisite)
