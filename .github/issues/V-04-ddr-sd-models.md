---
id: V-04
title: "VERIFICATION: DDR3 and SD card simulation models, fast and full-stack"
labels: [verification, P1, "area:memory", "area:storage", "size:M"]
depends_on: [MEM-01]
---

## What

The two external-device models the memory and storage blocks cannot be verified
without, each in two forms: a fast behavioural model for everyday benches, and a
full-fidelity one for a small number of slow, thorough tests.

## Why two forms of each

`rtl/RTL_PLAN.md` "Verification" item 4. The tension is simple: a cycle-accurate
Micron DDR3 model plus the litedram PHY in Icarus is slow enough that no bench using
it will be run on every commit, and a bench nobody runs is a bench that does not
exist. But a purely behavioural model hides exactly the timing problems that the full
model would catch.

So: fast models for `MEM-02`, `MEM-03`, `CMP-*`, `ST-01` and the small `V-03` run —
which is almost everything — and one slow full-stack test each that runs nightly and
would catch what the fast model abstracts away.

## Deliverables

- `rtl_tests/common/stubs/ddr_fast.v` — behavioural memory at the litedram user
  interface: configurable latency, configurable refresh stalls, byte masking,
  optional response reordering
- `rtl_tests/common/utoss_tb/ddr.py` — Python-side reference memory for scoreboarding
- A wiring path for the **full** DDR3 model (the Micron Verilog model, or litedram's
  own simulation target) used by one nightly test
- `rtl_tests/common/stubs/sd_card_fast.v` or a cocotb SD model — SPI-mode card with
  the complete fault-injection set `ST-01` needs
- `rtl_tests/common/utoss_tb/sd_image.py` — reads the model's resulting card image so
  benches can assert on what was actually written
- `docs/SIM_MODELS.md` — what each model abstracts away, and therefore what it cannot
  catch

## Requirements

1. **`docs/SIM_MODELS.md` must state what the fast models do NOT model.** This is the
   most important deliverable here. A fast DDR3 model that silently ignores refresh
   gives every bench above it a false sense of timing margin, and the list of
   abstractions is what tells a reviewer which claims rest on the nightly test instead.
2. **The fast DDR model must inject the worst-case refresh stall measured in
   `MEM-01`**, configurably. That stall is what `DP-05`'s FIFO depth is sized against,
   so it has to be reproducible in a fast bench rather than only in the nightly one.
3. **The fast DDR model must be able to return responses out of order**, if the
   chosen litedram configuration can. `MEM-02` requirement 6 depends on being able to
   test that.
4. **The SD model's fault set is driven by `ST-01`'s acceptance criteria**: reject a
   command, bad CRC response, long busy, persistent write error, refuse to initialise,
   wrong card type, no card. Each one must be a parameter, not a code edit.
5. **The SD model must behave like SDHC *and* SDSC**, including the addressing
   difference, because that difference is `ST-01` requirement 2 and it is otherwise
   untestable without two physical cards.
6. **Both Python-side models are the scoreboard**, not a second implementation of the
   DUT. The Verilog model answers the bus; the Python model says what the answer should
   have been. Keep them independent so a bug in one does not mask a bug in the other.
7. **The full-stack tests must actually run.** Wire them into CI as a scheduled
   nightly job with a generous timeout, with their results published. A nightly job
   whose failures nobody sees is the same as no job.

## Acceptance criteria

- `MEM-01`'s read/write benches pass against both the fast model and the full DDR3
  model, with identical functional results.
- Fast DDR model: configurable latency verified, refresh stall of a configured length
  verified to appear on the bus, byte masking exact, out-of-order responses verified.
- Fast DDR model is fast enough that the small `V-03` run fits in the CI job timeout.
  State the measured simulation time in the pull request.
- SD model: every fault in requirement 4 has a test proving the model produces it,
  and is referenced by an `ST-01` acceptance criterion.
- SD model in both SDHC and SDSC modes, with a test asserting the on-wire address
  differs correctly.
- `sd_image.py` reads back a card image and parses the `ST-01` card layout.
- One nightly CI job per full-stack model, whose failure is visible.
- `docs/SIM_MODELS.md` lists every abstraction in the fast models and names the
  nightly test that covers each.

## References

- `rtl/RTL_PLAN.md` "Verification" (item 4)
- `MEM-01` (measured latency and refresh stall), `MEM-02`, `ST-01`
