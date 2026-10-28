---
id: I-03
title: "INFRA: pin constraints (.lpf), CDC timing exceptions, and the top-level P&R gate"
labels: [infra, P1, "area:integration", "size:M"]
depends_on: [I-02, D-02, INT-01]
---

## What

The constraint files and the CI step that turns `tools/dev synth` from "it maps"
into "it closes timing on the real part, with the real pinout".

## Why it is separate from the per-module synthesis gate

The existing gate runs yosys per module and checks resource budgets. That proves
each block fits. It does not place anything, so it says nothing about whether the
assembled design meets 100 MHz, and nothing about whether the pixel bus can be
captured at all — which depends entirely on PCLK landing on a clock-capable pin in
the same bank as its data (`io_specs/fpga.yaml` `DCMI_RX` notes).

An unconstrained clock domain crossing is also one the tools will try, and fail,
to close timing across — and then report a violation that looks like a logic
problem.

## Deliverables

- `rtl/fpga/constraints/payload_top.lpf` — pin locations, I/O standards, drive
  strengths and slew for every top-level port
- `rtl/fpga/constraints/timing.py` or `.lpf` frequency and exception
  declarations: one clock constraint per domain, and an explicit exception for
  every CDC path
- `docs/PINOUT.md` — the pin map in a form the PCB work can consume
- `synth.place: true` plus `synth.lpf` and `synth.target_mhz` on the
  `INT-01` top-level bench, so P&R and the timing report become a CI gate

## Requirements

1. **Every top-level port is constrained**: location, I/O standard
   (`LVCMOS33` per `io_specs/fpga.yaml` unless `D-01` changes `VCCIO_CAM`), drive
   strength, slew. Take the drive strengths from the `io_specs` `electrical`
   blocks rather than from the tool defaults — `UART_CAM` deliberately specifies
   4 mA, and letting the default override that adds switching current and edge-rate
   EMI for no benefit.
2. **PCLK is on a clock-capable input pin in the same bank as `D[*]`.** This is a
   hard constraint from the datasheet, not a preference, and it is the thing most
   likely to be discovered too late. Resolve it with
   `io_specs/fpga.yaml` `open_items/bank-pin-assignment`.
3. **One frequency constraint per clock domain**, matching
   `rtl/ecp5_target.yaml` `clock_domains` — including `clk_px`, whose frequency
   is a camera property and comes from `D-01`.
4. **Every CDC path carries an explicit timing exception.** Cross-reference the
   list against the `fifo_async`, `sync_2ff` and `pulse_cdc` instances in the
   design: an instance with no exception is a bug in this file, and a constraint
   with no instance is a stale exception that may be hiding a real path. Make that
   cross-check a script if the instance count grows past a handful.
5. The `nextpnr_package` in `rtl/ecp5_target.yaml` must be the real TQFP-144
   package name before any timing number from this is believed (`D-02`,
   `open_items/nextpnr-package`). A clean report against the wrong package is
   worse than no report.
6. CI fails on a timing violation at the declared target frequency, and the
   reported `Max frequency for clock` per domain is published in the job summary
   so the margin is visible over time rather than only at the moment it runs out.

## Acceptance criteria

- `tools/dev synth --only payload_top` runs yosys **and** nextpnr-ecp5, and fails
  on a timing violation.
- The timing report shows every declared clock domain, with its achieved
  frequency.
- Every CDC instance in the design appears in the exception list; the pull request
  shows the cross-check.
- `docs/PINOUT.md` matches the `.lpf`, and both match `io_specs/fpga.yaml`.
- The ERC/logic checks in `kicad-ci.yml` still pass against the same pinout.

## References

- `rtl/ecp5_target.yaml` (`clock_domains`, `open_items/nextpnr-package`)
- `io_specs/fpga.yaml` (`DCMI_RX` notes, `banks`, `open_items/bank-pin-assignment`)
- `rtl/README.md` §6
