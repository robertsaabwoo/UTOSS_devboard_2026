---
id: D-03
title: "DECISION: cube memory layout in DDR3 — band-interleaved vs line-interleaved"
labels: [decision, P0, "area:memory", "area:compression", "size:M"]
depends_on: [D-02]
---

## What has to be decided

How a hyperspectral cube is laid out in DDR3: **BIL** (band-interleaved by
line), **BIP** (band-interleaved by pixel), or **BSQ** (band-sequential) — and
what the compressor's working-set access pattern is against that layout.

## Why it is a decision and not an implementation detail

From `rtl/RTL_PLAN.md` §5: this is the single biggest performance decision in
the memory block, because it determines whether the CCSDS 123 predictor's
neighbourhood fetch hits open DDR rows or thrashes them.

CCSDS 123.0-B predicts a sample from its **spatial** neighbours in the same band
(west, north, north-west) and its **spectral** neighbours (the same pixel in the
previous *P* bands). Those two demands pull in opposite directions:

- **BSQ** makes the spatial neighbours contiguous and the spectral neighbours
  one full band-image apart — megabytes of stride per spectral neighbour.
- **BIP** makes the spectral neighbours contiguous and the spatial neighbours a
  full line-of-all-bands apart.
- **BIL** is the usual compromise and is what most CCSDS 123 implementations
  assume, with a line buffer across bands held on-chip.

Get it wrong and the compressor stalls on DDR row activates, the camera write
port misses its deadline, and the fix is a rewrite of both `MEM-03` and `CMP-01`.

The second half of the decision is **how much of the working set lives in EBR**
rather than DDR. A full BIL line buffer is `line_width x bands x bit_depth`; on a
45F with ~1.9 Mbit of EBR that may or may not fit, and the answer bounds the
maximum swath width the payload can support.

## What to produce

- [ ] A written analysis, committed as `docs/MEMORY_LAYOUT.md`, covering:
      - the cube dimensions actually expected (swath width, bands, bit depth,
        lines per capture) — derive them from the 20 MB/s for 1–2 min/day
        requirement and the sensor shortlist in `D-01`
      - the chosen layout, and the predictor access pattern against it
      - DDR3 efficiency estimate: bursts per predicted sample, row-activate rate,
        and the resulting sustained bandwidth against what the fitted memory can
        actually deliver
      - the on-chip working set in bits, against `block_ram_blocks` in
        `rtl/ecp5_target.yaml`
      - the maximum swath width the chosen split supports, stated explicitly
- [ ] A small simulation or spreadsheet model backing the bandwidth number. A
      bandwidth estimate with no model behind it is a guess, and this is the
      number the whole architecture rests on.
- [ ] The decision reflected in the specs for `MEM-03` and `CMP-01` before
      either starts.

## Acceptance criteria

- The layout is named, the access pattern is written out, and the predicted DDR3
  efficiency is a number with a derivation.
- The on-chip buffer requirement fits the device's EBR with margin, or the swath
  width is reduced until it does.
- `MEM-03` and `CMP-01` can be specified in terms of concrete addresses and
  strides.

## Notes

This can be worked on before DDR3 RTL exists — it is analysis, and it is most
valuable precisely while nothing has been built against the wrong answer.

## References

- `rtl/RTL_PLAN.md` §5, §6
- CCSDS 123.0-B-2, §4 (prediction) and §3 (sample ordering)
