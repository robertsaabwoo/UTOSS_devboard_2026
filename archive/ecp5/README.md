# Archive: the ECP5 plan

The project first targeted a bare **Lattice ECP5 LFE5U-45F** with an open-source
flow, a hand-written DDR3 controller, SD writer, camera receivers and CCSDS 123
core. In October 2026 it moved to an AMD **Kria K26** SOM (see
`.github/issues/README.md` and the Drive document *PAY FPGA BOARD Project
Milestones*). INF-01 moved what was ECP5-only here.

Nothing in this folder is built, linted or checked by CI. It is kept because
parts of it are still useful reading:

| Path | What it was | Still useful for |
|---|---|---|
| `rtl/ecp5_target.yaml` | Synthesis target, resources, clock plan | Format of `rtl/target.yaml` |
| `rtl/RTL_PLAN.md` | The ECP5 RTL architecture and risks | CCSDS 123 notes, verification ideas |
| `hardware/devboard.kicad_sch` | ECP5 board schematic (no connectivity; 13 ERC errors) | Nothing; the carrier is B2.4 |
| `hardware/FLOORPLAN.md` | ECP5 board floorplan | PC104 constraints |
| `io_specs/` | Per-module pin and power specs for the ECP5 board | The format the hardware checks expect, for the carrier's own `io_specs/` |
| `docs/STATUS.md` | Measured ECP5 power and resource numbers (2026-10-07) | History |
| `docs/DEMO.md` | Demo runbook for the harness on the ECP5 flow | Rewriting a K26 demo |

The matching issue specifications are in `.github/issues/_superseded/`.
