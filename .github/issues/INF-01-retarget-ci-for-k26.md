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

- [ ] The synthesis job is replaced by either Yosys `synth_xilinx` as a rough
      resource check (runs on free GitHub runners) or Vivado on a self-hosted
      runner. Record which and why.
- [ ] Lint and cocotb cope with Xilinx primitives (`xpm_*`, AXI IP), through
      simulation stubs or by linting only our own modules.
- [ ] ECP5-only files are removed or moved to `archive/`.
- [ ] Once B2.4 starts, `kicad-ci` points at the new carrier schematic and its
      push and pull_request triggers are restored.

## References

- `.github/workflows/rtl-ci.yml`, `.github/workflows/kicad-ci.yml`
