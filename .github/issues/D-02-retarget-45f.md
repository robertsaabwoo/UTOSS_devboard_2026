---
id: D-02
title: "DECISION: retarget the board on LFE5U-45F and reconcile io_specs with the RTL target"
labels: [decision, P0, hardware, infra, "size:S"]
depends_on: []
---

## The problem

The RTL and the schematic currently disagree about the part, on purpose, and
that cannot survive to layout.

- `rtl/ecp5_target.yaml` targets **`LFE5U-45F-7TG144C`**. Everything in
  `scripts/run_synth_check.py` — the per-module budgets and the device ceiling —
  measures against the 45F.
- `io_specs/fpga.yaml` describes **`LFE5U-25F-7TG144C`**, with
  `resources.luts: 24000` and `block_ram_bits: 1032192`.

The RTL is on the 45F because the budget in `rtl/RTL_PLAN.md` does not close on
24k LUTs: DDR3 controller 3–5k, CCSDS 123 plus the Rice coder 5–10k, Camera Link
RX 2k+, SDIO 2k, infrastructure and CSRs 2k. That is plausible on a 24k part only
with no headroom at all, and ~126 KB of EBR is thin for a predictor that needs a
line buffer across bands. The 45F roughly doubles both.

## What to do

- [ ] Confirm from **Lattice's official pinout CSV** that `LFE5U-45F-7TG144C`
      and `LFE5U-25F-7TG144C` are pin-for-pin identical in TQFP-144 — bank
      boundaries and dedicated-function pins included, not just power and
      ground. (The 45F does exist in TQFP-144, so this is expected to hold, but
      "expected to hold" is not a thing to route a board on.)
- [ ] Price and check lead time and stock for the 45F in TQFP-144, in both
      commercial and industrial temperature grades.
- [ ] Update `io_specs/fpga.yaml`: `part_number`, `resources.luts`,
      `resources.block_ram_bits`, DSP count, PLL count, and the per-bank I/O
      counts (`open_items/bank-pin-assignment`) for the chosen part.
- [ ] Confirm `resources` and `utilization_ceiling` in `rtl/ecp5_target.yaml`
      line by line against **FPGA-DS-02012 Table 1.1**, and clear
      `open_items/confirm-device-resources`. The figures in there now are
      planning numbers from the family selection table, not transcribed, and
      somebody will eventually make an architectural decision on that headroom.
- [ ] Confirm how many PLLs are reachable in TQFP-144. The clock plan in
      `rtl/ecp5_target.yaml` `clock_domains` wants three or four domains; if the
      package exposes fewer PLLs than the die has, that is a design constraint
      worth knowing now rather than during `I-02`.
- [ ] Resolve `open_items/nextpnr-package` in `rtl/ecp5_target.yaml`:
      `nextpnr_package` is `CABGA381`, which does not match TQFP-144. Confirm
      nextpnr-ecp5's package name for TQFP-144 against the installed chipdb.
      Place-and-route against the wrong package produces plausible-looking
      timing for a part we are not building.
- [ ] Remove the "they disagree on purpose" note at the top of
      `rtl/ecp5_target.yaml` once they do not.

## Acceptance criteria

- One part number, in both files, with the datasheet table cited for every
  resource figure.
- `tools/dev synth` passes with a device ceiling derived from confirmed numbers.
- If `synth.place` is ever turned on, nextpnr runs against the real package.

## Why it is small but P0

It is a few hours of datasheet work. It is P0 because it is cheap now and very
expensive after the PCB is routed, and because every per-module resource budget
filed in the other issues is denominated in a device size that has not been
confirmed yet.

## References

- `rtl/ecp5_target.yaml`, `io_specs/fpga.yaml`
- `rtl/RTL_PLAN.md` "Risks"
- ECP5 and ECP5-5G Family Data Sheet FPGA-DS-02012
