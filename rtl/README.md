# RTL conventions

Every module in this repository follows these rules. They are not style
preferences — each one is here because breaking it causes a specific, expensive
failure on this project. Where a rule is enforced by a tool, the tool is named.

Target part, clock domains and resource ceilings live in
[`target.yaml`](target.yaml). What is to be built lives in the issues under
[`../.github/issues/`](../.github/issues/). How to run the checks lives in
[`../rtl_tests/README.md`](../rtl_tests/README.md).

---

## 1. Language and file layout

- **Verilog-2001 by default**, SystemVerilog only for interfaces and assertions
  where it clearly pays. Icarus Verilog is the simulator in CI, and its
  SystemVerilog support is partial — a module that only elaborates in a
  commercial simulator cannot be tested here.
- **One module per file. The file name is the module name.** Enforced by
  verilator's `DECLFILENAME`, and by `scripts/lint_rtl.py`, which lints every
  source file as a top module in its own right.
- Open every file with:
  ```verilog
  `timescale 1ns / 1ps
  `default_nettype none
  ```
  and close it with `` `default_nettype wire ``. Without `none`, a typo in a
  signal name silently becomes a new one-bit wire — a class of bug that costs
  days and that the compiler will otherwise never mention.
- Shared definitions go in `rtl/fpga/common/`. Headers are `.vh` and are
  guarded.

## 2. Everything is parameterized

- Widths, depths and counts are `parameter`s. No bare literal for a bus width,
  anywhere.
- Derived values are `localparam`, computed with `$clog2` — never a second
  hand-maintained parameter that can disagree with the first.
- Parameters are `UPPER_SNAKE_CASE`; signals and instances are
  `lower_snake_case`.
- **This is tested, not trusted.** Each bench declares several `param_sets` and
  the runner re-elaborates the module at each of them, including the smallest
  legal width. `utoss_tb.assert_param` then checks that the DUT really came up
  at the requested width, so a dropped parameter override fails instead of
  quietly testing the default three times.

```verilog
module my_block #(
    parameter integer WIDTH = 16,
    parameter integer DEPTH = 1024
) (
    ...
);
  localparam integer ADDR_W = $clog2(DEPTH);
```

## 3. Clocks and reset

- Clock and reset names come from `clock_domains` in `target.yaml`:
  `clk_sys`/`rst_sys_n`, the PL clock and reset from the Zynq PS. A
  single-domain leaf module may use plain `clk`/`rst_n`.
- **Reset is active-low, asynchronously asserted, synchronously released**, one
  per clock domain, produced by the Processor System Reset block in the Vivado
  design.
  Never cross a reset between domains unsynchronized.
- Every flop that holds state has a reset value. The FPGA is **power-gated**, so
  every imaging pass starts from a genuine cold start — anything relying on a
  bitstream-initialised value that the design later overwrites will behave
  differently on the first pass than on the rest.
- No `initial` blocks for reset state. They work in simulation and in the FPGA
  bitstream, and they hide exactly the bug above.
- One clock per module where possible. A module that needs two clocks is a CDC
  module, and CDC modules come from `rtl/fpga/common/` — not hand-rolled.

## 4. Coding rules the linter enforces

`scripts/lint_rtl.py` runs `verilator --lint-only -Wall` over every module and
fails the build on a warning. In particular:

| Rule | Why |
|---|---|
| No inferred latches (`LATCH`) | What you get is a routing-dependent timing hazard that simulates perfectly. |
| No implicit width change (`WIDTHEXPAND`, `WIDTHTRUNC`) | Silent truncation of a pixel or an address is invisible until a cube comes back corrupted. |
| No undriven or multiply-driven nets | Usually a typo or a copy-paste merge of two `always` blocks. |
| No combinational loops (`UNOPTFLAT`) | Will not route, and the error from the back end is unreadable. |
| Module name matches file name | Everything downstream is file-based. |

Other rules, enforced in review:

- `always @(posedge clk ...)` blocks use **non-blocking** (`<=`) assignment
  only. Combinational `always @(*)` blocks use **blocking** (`=`) only.
- No logic on a clock. No gated clocks — gate the **enable**, not the clock.
  (Clock gating on UltraScale+ means `BUFGCE` primitives and belongs in the
  Vivado block design, nowhere else.)
- No asynchronous feedback, no latch-based handshakes.
- State machines: `localparam` state encodings, one `always` block for the state
  register and one for next-state logic, and a `default:` arm that returns to a
  safe state. On a part susceptible to configuration upset, an FSM that can
  enter an unreachable state and stay there is a dead payload.

## 5. Stream interfaces

Every pipeline boundary uses the same AXI4-Stream subset, prefixed with the
port's name:

| Signal | Direction | Meaning |
|---|---|---|
| `<p>_tdata` | source → sink | payload |
| `<p>_tvalid` | source → sink | payload is valid |
| `<p>_tready` | sink → source | sink accepts on this edge |
| `<p>_tlast` | source → sink | last beat of a frame/line/packet (optional) |
| `<p>_tuser` | source → sink | sideband, meaning documented per module (optional) |

Three rules, all checked automatically by
`utoss_tb.check_stream_protocol`:

- **R1** `tvalid` must not depend on `tready`. A source may not wait to see
  `tready` before asserting `tvalid` — that combinational path across a module
  boundary is the classic AXI deadlock.
- **R2** Once `tvalid` is asserted it stays asserted until a transfer completes
  (`tvalid && tready` on a rising edge). Dropping it loses a beat.
- **R3** `tdata`, `tlast` and `tuser` are stable while `tvalid` is high and
  `tready` is low.

A transfer happens on a rising clock edge where `tvalid && tready`. Start every
new bench with `check_stream_protocol` running on each interface — a violation
here shows up as a corrupted image cube four blocks downstream, and finding it
there costs a week.

## 6. Clock domain crossings

- **Use the Xilinx XPM macros** (`xpm_cdc_single`, `xpm_cdc_pulse`,
  `xpm_cdc_async_rst`, `xpm_fifo_async`, `xpm_fifo_axis`), wrapped in
  `rtl/fpga/common/`. Do not hand-roll a synchronizer: every one is a separate
  place for a metastability bug to hide.
- Never synchronize a multi-bit bus with parallel two-flop synchronizers. Use
  the async FIFO, or a handshake around a held value.
- Every crossing is annotated in the timing constraints. An unconstrained
  crossing is one the tools will try — and fail — to close timing across.
- Any FIFO that can overflow **exposes an overflow counter** to the CSR block.
  Knowing that a cube dropped pixels is far more useful than silently
  corrupting a capture that cannot be re-taken.

## 7. K26 (Zynq UltraScale+) rules

- Target is the **Kria K26 SOM** (see `target.yaml`), developed on a KV260. The
  ARM cores own the camera, DDR and storage; the fabric gets data through AXI
  DMA and an AXI-Stream slot. Do not write RTL for something the PS already
  does.
- Vendor primitives and XPM macros (`xpm_*`, `RAMB36E2`, `DSP48E2`, …) are
  allowed, but **only inside a wrapper module in `rtl/fpga/common/`** whose
  interface is plain Verilog. A primitive sprinkled through the datapath makes
  the module unsimulatable in Icarus and unlintable in Verilator.
- Infer memory, do not instantiate it, unless you need a mode inference cannot
  express. Check what you got with `tools/dev synth`: a large buffer should land
  in block RAM, not LUTs, because that is how a 2 kB buffer becomes 16 000 LUTs.
- The CI synthesis gate is yosys `synth_xilinx`, a resource proxy. Timing and
  the real build are Vivado's; the block design is checked in as Tcl.
- Every module declares a **resource budget** in its `bench.yaml`, and CI holds
  it to it. Exceeding the budget is a decision somebody makes in a pull request,
  with a reason — not something that happens quietly over a term.

## 8. What a module is not done without

1. The module, following everything above.
2. A `bench.yaml` and a cocotb bench under `rtl_tests/<module>/<name>/`, with
   at least two parameter sets, that fails against a plausibly-broken DUT.
3. `tools/dev all` passing: lint, simulation, and the UltraScale+ mapping and budget
   check.
4. `status: ready` in `bench.yaml`. A pull request into `main` runs the test
   runner with `--strict`, where `wip` is itself a failure.
5. A short block comment at the top of the module naming the issue it
   implements (for example `B2.6`).

Scaffold all of this with:

```
tools/dev new fpga <module_name>
```
