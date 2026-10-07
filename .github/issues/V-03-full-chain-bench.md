---
id: V-03
title: "VERIFICATION: full-chain bench — synthetic cube in, compressed product out, bit-exact round trip"
labels: [verification, P1, "area:integration", "size:L"]
depends_on: [V-01, V-02, INT-01, CMP-04, ST-01]
---

## What

One bench that drives a synthetic cube into the camera model and asserts that what
comes off the SD card model, decompressed in software, is bit-identical to what went
in.

## Why it is the test that says "the payload works"

`rtl/RTL_PLAN.md` "Verification" item 3. Every other bench tests a module against a
well-behaved neighbour. This is the only test where the receiver, the framer, the CDC
FIFO, the arbiter, the addressing, the predictor, the entropy coder, the packer, the
framing and the storage writer all have to agree with each other about bit order,
sample ordering, geometry and alignment.

Most integration bugs in a chain like this are **agreement** bugs — two modules with
defensible but incompatible conventions. No module-level bench can find one.

## The round trip

```
tools/gen_cube.py
        |
        v
  V-02 camera model  -->  DP-01  -->  DP-04  -->  DP-05  -->  [DP-06]
                                                                  |
                                                      MEM-03 / MEM-02 / MEM-01
                                                                  |
                                              CMP-01 -> CMP-02 -> CMP-03 -> CMP-04
                                                                  |
                                                            ST-01 -> SD card model
                                                                  |
                                             Python: read card image, parse index
                                                                  |
                                              CMP-04 parser -> V-01 decompress
                                                                  |
                                                   compare, bit-exact, to the input
```

## Requirements

1. **Bit-exact, not approximate.** Lossless compression means the recovered cube is
   the input cube. Any difference is a bug, and the comparison must report the first
   differing sample's coordinates, not just that the arrays differ.
2. **Run it at a realistic scale as well as a small one.** A 16×16×4 cube is what
   runs in CI on every pull request. A full-geometry cube is the one that actually
   exercises the DDR ring, the arbiter under load, and the line buffers at their real
   size — run it nightly or on demand. A chain that works at 16×16 and not at
   2048×512 is the normal outcome, and the small test will not tell you.
3. **Run it with the whole chain stalling realistically**, not idealised: arbiter
   contention from a competing port, SD card going busy for its measured worst case
   (`ST-01` `max_busy_cycles`), backpressure on every interface. An integration test
   with no stalls proves the chain works in a condition that will never occur.
4. **Several cube contents.** Gradient (predictable, high ratio), noise
   (incompressible — this is the case that stresses the bit packer and the output
   bandwidth hardest), constant (enormous ratio, exercises the `U_MAX` and accumulator
   paths differently), and at least one real hyperspectral cube.
5. **Several geometries**, including the degenerate ones every module was asked to
   handle: `bands=1`, `width=1`, `lines=1`, and one geometry whose line length is not
   a multiple of the DDR word.
6. **Measure and publish, from the real chain**: achieved compression ratio, total
   capture-to-card wall time in simulated cycles, peak occupancy of every FIFO, and
   worst-case wait per arbiter port. These are the numbers `INT-01` requirement 6
   predicted from the module-level measurements, and this is where the prediction is
   checked. A discrepancy is a finding.
7. **Every telemetry counter must read zero** (or its expected value) at the end of a
   clean run. A successful round trip with a non-zero overflow count is not a success —
   it means the chain happened to work while losing data somewhere, and the next run
   may not be so lucky. Assert on all of them.

## Acceptance criteria

- Small-cube round trip bit-exact, running in CI on every pull request within the
  job timeout.
- Full-geometry round trip bit-exact, as a separate on-demand or nightly job.
- Bit-exact across every cube content in requirement 4 and every geometry in
  requirement 5.
- Bit-exact with realistic stalling per requirement 3, and identical output to the
  unstalled run.
- All telemetry counters assert clean per requirement 7.
- A run with an **injected** fault at each stage (camera short frame, forced FIFO
  overflow, forced SD write error) where the bench asserts the failure is **reported**
  in the CSR and the product is **marked bad** — rather than a silently wrong cube
  being written. This is as important as the clean path: the mission's real requirement
  is never to return a corrupt cube that looks good.
- The measurements in requirement 6 published and compared against `INT-01`'s
  predictions.

## Notes

This issue is not a lot of code — it is a lot of careful assertion. Budget time for
debugging *other* modules: this is where their disagreements surface, and the issues
that get filed from this bench are the point of it.

## References

- `rtl/RTL_PLAN.md` "Verification" (item 3)
- `V-01` (software model), `V-02` (camera model), `INT-01` (the chain and its
  predicted margins)
