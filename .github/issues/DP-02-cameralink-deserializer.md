---
id: DP-02
title: "RTL: Camera Link receiver — 7:1 LVDS deserializer, bit alignment, deskew (BLOCKED on D-01)"
labels: [rtl, blocked, P1, "area:datapath", "size:XL"]
depends_on: [D-01, I-01, I-02]
blocked_by_decision: D-01
---

## Blocked — but one of the two likely outcomes

**Do not start the RTL.** It only applies if `D-01` chooses Camera Link, and if
`D-01` chooses GigE or parallel this issue closes.

But note that this is **not** a remote contingency: at the 2026-09-05 meeting
the client stated the interface as Camera Link or GigE, so this and `DP-03` are
the two probable answers. The parallel receiver in `DP-01` is the fallback, not
the baseline.

That makes the "before any RTL is written" checklist below urgent rather than
hypothetical — in particular the LVDS feasibility question and the
off-the-shelf-receiver-chip option. Both are answerable now, while `D-01` is
still open, and either could rule Camera Link out on hardware grounds before a
line of Verilog is written.

## Why it is the hardest block in the project

The **LFE5U has no SERDES**. On a part with hard serialisers a Camera Link
receiver is a vendor IP instantiation. Here it is:

- LVDS input buffers on four data pairs plus a clock pair
- a **7:1 DDR gearbox** built by hand from `IDDRX` primitives plus a PLL phase
  shift
- per-channel **bit alignment**: find the 7-bit word boundary in each serial
  stream independently
- per-channel **deskew**: the four channels do not arrive aligned, and the training
  FSM has to correct that
- Base/Medium/Full **word reassembly** into pixels
- continuous monitoring, because alignment can be lost and silently staying
  misaligned produces plausible-looking garbage

Every one of those is a block in its own right, and the bit-alignment training FSM
is the kind of thing that works in simulation and then needs an oscilloscope.

## Rough scope if it goes ahead

| Piece | Est. LUTs |
|---|---|
| IDDRX gearbox, 4 channels | 400 |
| Bit alignment FSM per channel | 600 |
| Deskew and word reassembly | 600 |
| Monitoring and telemetry | 400 |
| **Total** | **~2000+** |

Plus a PLL with a phase-shift capability, and a dedicated simulation model that
can inject channel skew and bit slips — without that model this cannot be verified
at all.

## If this is chosen, before any RTL is written

- [ ] Confirm which Camera Link configuration (Base / Medium / Full) the sensor
      uses, and the resulting channel count and pixel clock.
- [ ] Confirm the LFE5U-45F in TQFP-144 has enough **true LVDS-capable input
      pairs** in one bank, at the required rate, with `VCCAUX` powering the
      differential input comparators (`io_specs/fpga.yaml` `VCCAUX` notes).
      The ECP5 LFE5U's LVDS input support and the achievable bit rate per pair are
      the gating facts; if they do not support the sensor's rate, Camera Link is off
      the table regardless of RTL effort.
- [ ] Confirm the PLL phase-shift resolution is fine enough to centre the sampling
      point, at the required bit rate.
- [ ] Decide whether an off-the-shelf Camera Link receiver chip in front of the
      FPGA is cheaper than ~2000 LUTs and a term of schedule. That is a serious
      option and it should be priced before this is committed to.
- [ ] Write the simulation model first. A hand-built deserializer with no model
      that can inject skew and bit slips cannot be verified, and an unverified
      deserializer will not work on hardware.

## Acceptance criteria (if it proceeds)

Full specification to be written once `D-01` resolves and the configuration is
known. At minimum it must include: alignment acquired from a cold start within a
bounded time; alignment **re-acquired** after an injected bit slip; a channel skew
sweep across the full specified range; and a loss-of-alignment telemetry flag that
asserts rather than the receiver silently delivering misaligned words.

## References

- `rtl/RTL_PLAN.md` §1 (Camera Link)
- `io_specs/fpga.yaml` (`VCCAUX` powers the differential input comparators;
  `chip_family: ECP5 (LFE5U — no SERDES)`)
