---
id: D-01
title: "DECISION: pick the camera interface (Camera Link vs GigE Vision vs parallel)"
labels: [decision, P0, hardware, "area:datapath", "size:M"]
depends_on: []
---

## What has to be decided

Which physical and protocol interface the sensor presents to the FPGA. Three
candidates, from `rtl/RTL_PLAN.md` §1:

1. **Camera Link** — LVDS pairs with a 7:1 serialisation.
2. **GigE Vision** — RGMII, MAC, UDP/IP, GVSP streaming, GVCP control.
3. **Plain parallel (DCMI-style)** — PCLK, HSYNC, VSYNC, D[13:0]. What
   `io_specs/camera.yaml` and `io_specs/fpga.yaml` currently assume.

## Start here: the specs and the client disagree

At the 2026-09-05 bus/payload meeting the client stated the interface as
**Camera Link or GigE** — explicitly *not* the DCMI-style parallel bus that
`io_specs/camera.yaml` and `io_specs/fpga.yaml` describe today. The FPGA is
replacing a Raspberry Pi and an unmaintainable microcontroller camera driver,
and both of those read a camera, not a raw sensor.

So the first job of this issue is not a trade study, it is **confirming which
of the two the client means**, and then correcting the io_specs. The parallel
option stays on the list only because it is what the repository currently
asserts and because it applies if the part turns out to be a raw sensor module
rather than a camera — but it should be treated as the least likely outcome,
not the default.

That reordering matters for scheduling: both of the likely answers are the
expensive ones. `DP-02` (Camera Link, ~2000 LUTs and a hand-built
deserializer on a part with no SERDES) and `DP-03` (GigE, ~4000 LUTs plus a
PHY, magnetics and a connector on the PCB) are each larger than the
compressor's entropy coder.

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

- [ ] **Confirm with the client (Boris / Joe Dai) which of Camera Link or GigE
      Vision the camera actually presents**, and whether a specific camera has
      been selected on their side. This is one email and it removes the largest
      unknown in the RTL schedule.
- [ ] A shortlist of two or three candidate camera modules that meet the science
      requirement, with datasheets, lead time and price. The payload is
      hyperspectral at ~20 MB/s for 1–2 min/day, within a ~$2000 total cost
      envelope.
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

Everything downstream of the pixel stream is **independent of this decision**:
`DP-04` onward are written against the stream interface in `rtl/README.md` §5,
not against the camera. So the rest of the datapath, the memory subsystem and
the whole compression chain can proceed at full speed while this is settled.

`DP-01` (parallel) is specified and buildable, and remains the right thing to
build if the answer turns out to be a raw sensor module. It is also by far the
cheapest way to get a working pixel source into the chain for integration
testing. But do not treat it as the expected answer — the client's stated
requirement points at `DP-02` or `DP-03`.

## References

- `rtl/RTL_PLAN.md` §1
- `io_specs/camera.yaml`, `io_specs/fpga.yaml` (`DCMI_RX`, `open_items`)
- `UTAT Meeting.txt`: "How flexible should our pinouts be?", "need to get reset
  controls of the camera and all other controls of the camera that the ground
  station can have control of"
- 2026-09-05 bus/payload meeting: interface stated as Camera Link or GigE; the
  FPGA replaces an always-on Raspberry Pi and an unmaintainable microcontroller
  camera driver
