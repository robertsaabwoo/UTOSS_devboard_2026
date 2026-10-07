---
id: D-01
title: "DECISION: pick the camera interface (Camera Link vs GigE Vision vs parallel)"
labels: [decision, P0, hardware, "area:datapath", "size:M"]
depends_on: []
---

## What has to be decided

Which physical and protocol interface the sensor presents to the FPGA. Three
candidates, from `rtl/RTL_PLAN.md` §1:

1. **Plain parallel (DCMI-style)** — PCLK, HSYNC, VSYNC, D[13:0]. What
   `io_specs/camera.yaml` and `io_specs/fpga.yaml` currently assume.
2. **Camera Link** — LVDS pairs with a 7:1 serialisation.
3. **GigE Vision** — RGMII, MAC, UDP/IP, GVSP streaming, GVCP control.

## Why this is the first decision on the board

It is the largest single fork in the RTL budget and it is on the critical path
for roughly a third of the work:

- **Parallel** — the receiver is a few hundred LUTs. `DP-01` as specified.
- **Camera Link** — the LFE5U has **no SERDES**, so the 7:1 deserialiser is
  ours to build out of `IDDRX` primitives plus PLL phase shift, with
  per-channel bit alignment and deskew training. `DP-02`, and the hardest
  single block in the project.
- **GigE Vision** — an Ethernet MAC (use an existing core), then UDP/IP, then a
  GVSP depacketiser that has to cope with reordering and loss because GVSP
  streams over UDP. `DP-03`, and it also changes the PCB: magnetics, an RJ45 or
  M12, and a PHY.

It also changes the **pin budget and the bank plan** (`io_specs/fpga.yaml`
`open_items/bank-pin-assignment`), the **I/O voltage** (a 1.8 V sensor bus makes
`VCCIO_CAM` a separate rail and turns the LVCMOS33 edge in
`io_specs/camera.yaml` into LVCMOS18), and therefore the layout. Discovering it
after routing is expensive.

## What to produce

- [ ] A shortlist of two or three candidate sensor modules that meet the science
      requirement, with datasheets, lead time and price. The payload is
      hyperspectral at ~20 MB/s for 1–2 min/day.
- [ ] For each: interface type, data width, bit depth, pixel clock, sync
      polarity, which PCLK edge data is valid on, I/O voltage, power rails and
      their sequencing.
- [ ] The decision, written down with its reasoning, in
      `io_specs/camera.yaml` — replacing the `PLACEHOLDER` fields, not sitting
      beside them.
- [ ] `io_specs/fpga.yaml`: resolve `open_items/dcmi-bus-parameters`, and set
      `VCCIO_CAM` to the sensor's actual I/O voltage.
- [ ] Close whichever of `DP-02` / `DP-03` the decision rules out, with a
      comment saying why.

## Acceptance criteria

- `python3 scripts/check_logic_spec.py --module camera` and `--module fpga`
  pass against **real transcribed numbers**, with no `PLACEHOLDER` remaining on
  any net involved in the video bus.
- `DP-01`, `DP-02` or `DP-03` is unblocked and the other two are closed.
- The pin count and bank requirement are stated concretely enough that the
  pinout can be fixed (`open_items/bank-pin-assignment`).

## Notes

Until this resolves, the RTL proceeds on the **parallel** assumption, because
that is what the io_specs describe and because nothing downstream of the pixel
stream depends on the choice. `DP-04` onward are written against the stream
interface in `rtl/README.md` §5, not against the camera.

## References

- `rtl/RTL_PLAN.md` §1
- `io_specs/camera.yaml`, `io_specs/fpga.yaml` (`DCMI_RX`, `open_items`)
- `UTAT Meeting.txt`: "How flexible should our pinouts be?", "need to get reset
  controls of the camera and all other controls of the camera that the ground
  station can have control of"
