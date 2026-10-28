---
id: V-01
title: "VERIFICATION: CCSDS 123 golden software model and bit-exact comparison harness"
labels: [verification, P0, "area:compression", "size:L"]
depends_on: []
---

## What

A software CCSDS 123 compressor and decompressor in Python, validated against the
standard, plus the harness that drives the same cube through it and through the RTL
and compares the results bit for bit.

## Why this is first, before any compression RTL

`rtl/RTL_PLAN.md` names it outright: *"Bit-exact compressor check — same cube
through a software CCSDS 123 implementation and through the RTL, compare. The most
valuable test in the project by a wide margin."*

The reason is specific. A compressor is either bit-exact or it is useless: a
conforming decompressor on the ground cannot decode a bitstream that diverges by one
bit, and the failure is not graceful degradation, it is garbage from the point of
divergence. There is no way to tell by inspection whether `CMP-01` is correct. With
the model, every disagreement is localised to a sample, a band and an intermediate
value — which turns a week of guessing into an afternoon.

It is also the only way to answer the questions that other issues depend on:

- `D-04` needs the **real compression ratio** to decide whether the pass fits in DDR
  and whether SPI-mode SD is fast enough.
- `DP-06` needs to know whether on-board correction improves the ratio enough to be
  worth an FPGA block.
- `CMP-01` needs its configuration decided, and the model is where configurations are
  cheap to compare.
- `CMP-02` needs the entropy-coder choice settled by measurement.

So this unblocks four decisions as well as the RTL.

## Deliverables

- `tools/ccsds123/` — the reference implementation
  - `predictor.py` — full CCSDS 123.0-B predictor, every configuration parameter
    exposed
  - `entropy.py` — sample-adaptive encoder, and the 121.0-B Rice coder if `CMP-02`
    needs the comparison
  - `pack.py` — bit packing matching `CMP-03`
  - `decompress.py` — the inverse. **Non-negotiable:** a compressor with no
    decompressor cannot be validated, and the ground segment needs one anyway.
  - `cli.py` — compress/decompress a cube file from the command line
- `tools/ccsds123/tests/` — unit tests, including the standard's test vectors
- `rtl_tests/common/utoss_tb/golden.py` — the cocotb-side harness that runs the model
  and compares against the DUT, with per-sample mismatch reporting
- `tools/gen_cube.py` — synthetic cube generator (gradient, noise, step, worst case)
- `docs/GOLDEN_MODEL.md` — what is implemented, what is not, and how it was validated

## Requirements

1. **Validate against something external, not only against itself.** A
   self-consistent wrong implementation passes every test you write. Options, in order
   of preference:
   - the test vectors published with CCSDS 123.0-B
   - cross-check against an existing open implementation (ESA's or a published
     academic one) on the same cube
   - cross-check compress-then-decompress round trip *and* compare intermediate values
     (local sums, local differences, predicted samples, weights) against hand-worked
     examples from the standard's text
   Do at least two of these and say which in `docs/GOLDEN_MODEL.md`.
2. **Expose every intermediate value.** The model must be able to dump, per sample:
   local sum, local differences, weight vector, predicted sample, residual, mapped
   residual, codeword and its length. The RTL comparison needs these to localise a
   mismatch; "the output differs at byte 4096" is not a debuggable finding.
3. **Every configuration parameter is a parameter**, matching `CMP-01`'s parameter
   list exactly: *P*, Ω, register size, full/reduced, local sum type, accumulator
   initialisation, `U_MAX`. The names should match the RTL so a configuration can be
   compared by reading.
4. **The harness reports the first mismatch with context**: sample coordinates, both
   values, and the intermediate values that led to each. A diff of two byte streams is
   not a usable failure report for this.
5. **Speed matters enough to matter.** A pure-Python model over a 2048×512×200 cube is
   slow. Use numpy where the algorithm allows, and provide a small-cube mode for CI.
   The full cube is a nightly or on-demand run, not a per-commit one.
6. **Cube format**: pick a simple one (raw plus a sidecar header, or ENVI, which is
   standard for hyperspectral data and lets real AVIRIS cubes be used directly) and
   document it. `tools/gen_cube.py` and the CI harness both use it.

## Measurements to produce, which other issues depend on

- [ ] Compression ratio on representative data (real hyperspectral if obtainable —
      AVIRIS cubes are public), across several configurations. → `D-04`, `CMP-01`
- [ ] Compression ratio with and without the sensor correction of `DP-06`. → `DP-06`
- [ ] Sample-adaptive versus Rice coder on the same cube. → `CMP-02`
- [ ] Ratio versus *P*, so the area/ratio trade in `CMP-01` has data behind it.

Put these in `docs/GOLDEN_MODEL.md` and link them from the issues that need them.

## Acceptance criteria

- `compress` then `decompress` recovers the original cube exactly, for every
  configuration, on every synthetic cube and at least one real one.
- External validation per requirement 1, documented.
- Unit tests covering every edge case `CMP-01` must handle: first sample, first line,
  first column, last column, band 0, bands below *P*, `bands=1`, `width=1`, `lines=1`,
  minimum and maximum sample values.
- `tools/gen_cube.py` produces a gradient cube, a uniform-noise cube, a constant cube
  (which should compress enormously, and is a good sanity check), and a worst-case
  incompressible cube.
- The cocotb harness demonstrably catches an injected error: deliberately perturb one
  weight update in a copy of the model and confirm the harness reports the exact
  sample. A comparison harness that has never been shown to fail is a harness nobody
  should trust.
- `tools/ccsds123` has its own CI job (pure Python, no container needed) running the
  unit tests.
- The four measurements above are published.

## Notes

This is a substantial piece of software and it is not Verilog, so it may suit a
different person than the RTL issues. It is also the single highest-leverage thing
anyone can be working on right now: it is on the critical path for `CMP-01`, `CMP-02`,
`CMP-03`, `CMP-04`, `V-03`, `D-04` and `DP-06`, and it is not blocked on any
hardware decision.

## References

- CCSDS 123.0-B-2 and the Green Book CCSDS 120.2-G-2
- CCSDS 121.0-B-3
- `rtl/RTL_PLAN.md` "Verification" (item 1)
