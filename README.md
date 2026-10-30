# UTOSS Devboard 2026

The open-source FPGA payload board from UTOSS 2026: the data-handling board for
UTAT's hyperspectral imaging payload. It is built around an **AMD Kria K26 SOM**
(Zynq UltraScale+), developed first on a **KV260** dev kit, and later on our own
carrier board.

On the K26, the ARM cores run Linux and handle the USB 3.0 camera, DDR and
storage. The FPGA fabric carries the frame path and the **CCSDS 123** lossless
hyperspectral compressor.

The work is split into four Builds, ending in a **design review in January 2027**
and a **final demo in May 2027**. See [Plan and issues](#plan-and-issues).

---

## Quick start

You need **Docker** and **make**. Everything else (Icarus Verilog, Verilator,
Yosys, cocotb) runs inside the same container CI uses, so a result on your laptop
is the CI result.

```bash
make all                                    # lint + simulate + synthesise: exactly what CI runs
make sim                                    # every testbench, at every parameter set
make sim   ARGS="--only reg_handshake"      # one testbench
make waves ARGS="--only reg_handshake"      # same, plus an .fst waveform per run
make lint                                   # Verilator lint over all RTL
make synth                                  # map to UltraScale+ and check resource budgets
make shell                                  # a shell inside the container
```

The first run builds the container (a few minutes). After that, `make all` takes
about two minutes.

Results land in `build/` (not committed). The runner prints each waveform's path,
for example
`build/rtl/examples/reg_handshake/default/sim_build/reg_handshake.fst`. Open it in
[GTKWave](https://gtkwave.sourceforge.net/) or [Surfer](https://surfer-project.org/).

Windows works from Git Bash, PowerShell or cmd: `make` picks the right wrapper.
Without make, use `tools\dev.cmd all` (Windows) or `tools/dev all`
(Linux, macOS, WSL).

## New here? Start with the FIFO exercise

[`rtl/examples/fifo.v`](rtl/examples/fifo.v) is an empty FIFO with its spec and
a ready-made set of tests. Write it until `make sim ARGS="--only fifo"` passes.
Step-by-step instructions are in
[`rtl/examples/README.md`](rtl/examples/README.md).

## Writing a module

```bash
tools/dev new fpga frame_crc        # Windows: tools\dev.cmd new fpga frame_crc
```

That creates three files, which already lint, simulate and synthesise green:

| File | What it is |
|---|---|
| `rtl/fpga/frame_crc.v` | the module skeleton, with the repo conventions in its header |
| `rtl_tests/fpga/frame_crc/bench.yaml` | the manifest CI discovers: sources, parameter sweep, resource budget |
| `rtl_tests/fpga/frame_crc/test_frame_crc.py` | the cocotb testbench |

There is no CI file to edit and no list to register in: any directory with a
`bench.yaml` is found and run. Fill in the module and the tests, set the budget
from the first `make synth`, and open a pull request.

Read these first:

- [`rtl/README.md`](rtl/README.md) covers the RTL conventions: clocks, resets,
  CDC, streaming interfaces and the K26-specific rules.
- [`rtl_tests/README.md`](rtl_tests/README.md) covers how benches work, the
  `bench.yaml` fields, the shared test helpers and what makes a test worth
  having.
- [`rtl/examples/`](rtl/examples/) holds the FIFO exercise and
  `reg_handshake`, a deliberately trivial register the harness uses as its
  self-test. Neither is a starting point for any issue: the payload RTL is
  yours to write.

## What CI checks

[`rtl-ci`](.github/workflows/rtl-ci.yml) runs on every push and pull request
that touches RTL, tests or tooling:

| Job | Checks | Fails when |
|---|---|---|
| **Lint** | `verilator --lint-only -Wall` on every module, each as its own top | latches, width mismatches, undriven or multiply-driven signals, combinational loops, or an `rtl/` file no bench compiles |
| **Simulation** | every cocotb bench, once per `param_set` | any test fails, a bench produces no tests, a parameter override did not apply, or a simulation hangs |
| **Waveforms** | the reference bench with `--waves` | no `.fst` is written; the dump is attached to the run for download |
| **Synthesis** | `yosys synth_xilinx -family xcup` per module | a module exceeds its LUT / FF / BRAM / URAM / DSP budget in `bench.yaml` |

Benches marked `status: wip` may fail on a feature branch without turning CI red,
but a pull request into `main` runs strict, where `wip` itself is a failure.

Synthesis here is a resource **proxy**, not sign-off: timing, placement and the
block design belong to Vivado. The target part and its resource numbers are in
[`rtl/target.yaml`](rtl/target.yaml).

[`kicad-ci`](.github/workflows/kicad-ci.yml) (schematic ERC, I/O spec and power
checks) is **paused**. It runs only when started by hand, and comes back pointed
at the carrier-board schematic when that work starts (issue B2.4).

## Plan and issues

The work follows the Kria K26 milestone plan, with one GitHub milestone per Build:

| Milestone | Outcome |
|---|---|
| **Build 1: Foundations** | toolchain and blinky on the KV260, test data, AXI DMA loopback, CCSDS 123 groundwork |
| **Build 2: Interfaces proven; custom board designed** | camera library, live pipeline on replayed data, carrier schematic and layout, frame path in fabric; **design review, Jan 2027** |
| **Build 3: Custom board brought up** | bring-up, interface tests, real camera, CCSDS 123 in fabric |
| **Build 4: End-to-end and final demo** | rework, end-to-end on the carrier, soak test; **final demo, May 2027** |
| **After Build 4: space-grade PAY board** | flight parts, fault protection, environmental; tracked for visibility |

Work runs in three streams, labelled `stream:camera`, `stream:hardware` and
`stream:rtl`. **Where to start** for each role is in
[`.github/issues/README.md`](.github/issues/README.md). Every issue has its
specification as a file in [`.github/issues/`](.github/issues/), and
[`scripts/sync_issues.py`](scripts/sync_issues.py) keeps GitHub in step with them.

## Repository layout

| Path | Contents |
|---|---|
| [`rtl/`](rtl/) | Verilog. `rtl/fpga/` holds the payload modules (created by `tools/dev new`); `rtl/examples/` holds the worked examples. |
| [`rtl_tests/`](rtl_tests/) | cocotb benches, one directory per module, plus the shared helpers in `common/utoss_tb/`. |
| [`scripts/`](scripts/) | the test, lint and synthesis runners CI calls, the module scaffolder and the issue sync. |
| [`tools/`](tools/) | `dev`, `dev.ps1` and `dev.cmd`, the entry points `make` wraps. |
| [`docker/`](docker/) | the toolchain image, with pinned tool versions. |
| [`.github/`](.github/) | workflows, issue specifications, labels and milestones. |
| `hardware/`, `libraries/`, `spice/` | KiCad and power-simulation layout for the carrier board (Build 2); placeholders for now. |
| [`archive/ecp5/`](archive/ecp5/) | the earlier Lattice ECP5 design, kept for reference. Not built or checked. |

## Contributing

1. Take an issue. The ones with no dependencies are listed in
   [`.github/issues/README.md`](.github/issues/README.md).
2. Branch from `main`, then `tools/dev new ...` or edit an existing module.
3. Run `make all` until it is green.
4. Open a pull request that names the issue. CI must pass, and `wip` benches must
   be flipped to `ready`.
