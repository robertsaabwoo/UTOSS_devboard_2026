---
id: INF-01
title: "INFRA: retarget CI and the repo layout from the ECP5 to the K26"
labels: ["stream:all", infra, P1, "size:M"]
milestone: "Build 1: Foundations"
depends_on: []
---

## What

The repository and CI were built for a Lattice ECP5 with an open-source flow.
Keep what is vendor-neutral; retire the rest.

| Keep | Retire or replace |
|---|---|
| `rtl / Lint (verilator)` | `rtl / ECP5 synthesis & resource budget` (Yosys + nextpnr-ecp5) |
| `rtl / cocotb simulation` and `rtl_tests/` | `rtl/ecp5_target.yaml` |
| `bench.yaml` validation and the coverage rule | `rtl/fpga/reg_handshake.v` placeholder |
| | `kicad-ci` against `hardware/devboard.kicad_sch` (paused; that was the ECP5 board) |
| | ECP5 power numbers in `docs/STATUS.md` |

## Done when

- [x] The synthesis job is replaced by Yosys `synth_xilinx -family xcup` as a
      resource check, because it runs on free GitHub runners; Vivado owns
      placement and timing. Target in `rtl/target.yaml`.
- [ ] Lint and cocotb cope with Xilinx primitives (`xpm_*`, AXI IP), through
      simulation stubs or by linting only our own modules. Needed before the
      first module that instantiates an XPM macro (B1.5).
- [x] ECP5-only files are moved to `archive/ecp5/` (see its README).
- [ ] Once B2.4 starts, `kicad-ci` points at the new carrier schematic and its
      push and pull_request triggers are restored.

## References

- `.github/workflows/rtl-ci.yml`, `.github/workflows/kicad-ci.yml`
