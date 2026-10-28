---
id: MEM-01
title: "RTL: DDR3 controller integration (litedram) plus a simulation model — do NOT write the PHY"
labels: [rtl, P0, "area:memory", "size:L"]
depends_on: [I-02, D-02]
---

## What

Bring up a DDR3 controller and make it usable from our RTL and testable in
simulation. ~2 GB of volatile memory is mandatory: the ECP5's EBR (~237 KB on the
45F) cannot hold a hyperspectral cube.

## The first and most important requirement: do not write the PHY

From `rtl/RTL_PLAN.md` §5. Use **litedram** — open source, generates Verilog,
well proven on ECP5 — or Lattice's own IP. A DDR3 PHY involves write levelling,
read calibration, per-bit deskew and a lot of analogue-adjacent timing. It is
months of work, it is already done, and it is not where this project's value is.

What we write is the thin layer around it: `MEM-02` (arbiter) and `MEM-03` (cube
addressing). This issue is about integration, which is a real piece of work in its
own right.

## Deliverables

- A pinned litedram configuration committed to the repo (the generator input, not
  only its output), so the controller can be regenerated reproducibly
- `rtl/fpga/ddr_wrapper.v` — a plain-Verilog wrapper presenting one simple
  request/response port to `MEM-02`
- `rtl_tests/common/stubs/ddr_model.v` — or litedram's own simulation model, wired
  into the bench flow
- `rtl_tests/common/utoss_tb/ddr.py` — a Python-side memory model for scoreboarding
- A bench proving read-after-write correctness through the whole stack
- `docs/DDR_BRINGUP.md` — the configuration chosen, the memory part fitted, and the
  calibration failure modes

## Integration decisions to make and document

- [ ] **Which DDR3 part**, its speed grade, and its width. This fixes `clk_ddr` in
      `rtl/ecp5_target.yaml` and the achievable bandwidth that `D-03` and `MEM-02`
      are budgeted against.
- [ ] **litedram or Lattice IP.** litedram is open source — relevant for a project
      publishing its sources — and is well proven on ECP5 specifically. Lattice IP
      ties the build to Diamond, which the whole CI flow here does not use. This is
      effectively decided; write down why.
- [ ] **Whether litedram supplies its own PLL** for the DDR domain, which likely
      removes `pll_ddr` from `I-02`. Check before writing that wrapper.
- [ ] **How the generated Verilog enters the repository**: vendored output, or
      generated during the build. Vendored is reproducible and reviewable and makes
      CI self-contained; generated is smaller but adds a Python/Migen toolchain to
      the container. Vendoring is probably right — note the version and the exact
      generator invocation alongside it.
- [ ] **How it is simulated.** This is the part that determines whether anything
      downstream can be verified at all. A full DDR3 model plus PHY in Icarus is slow;
      a behavioural model at the controller's user interface is fast and is enough for
      `MEM-02`, `MEM-03` and `CMP-*`. Probably: do both — a fast behavioural model for
      everyday benches, and one slow full-stack test for `V-04`.

## Wrapper interface

```verilog
module ddr_wrapper #(
    parameter integer ADDR_W = 28,
    parameter integer DATA_W = 128,       // litedram user port width
    parameter integer ID_W   = 4
) (
    input  wire                 clk_sys,
    input  wire                 rst_sys_n,

    // DDR3 pads -- straight through to the generated controller
    // (names follow the generated core; do not rename them)

    // One simple port for MEM-02
    input  wire                 cmd_valid,
    output wire                 cmd_ready,
    input  wire                 cmd_write,
    input  wire [ADDR_W-1:0]    cmd_addr,
    input  wire [ID_W-1:0]      cmd_id,
    input  wire [DATA_W-1:0]    wr_data,
    input  wire [DATA_W/8-1:0]  wr_mask,

    output wire                 rd_valid,
    input  wire                 rd_ready,
    output wire [DATA_W-1:0]    rd_data,
    output wire [ID_W-1:0]      rd_id,

    // Status, to I-02 and the CSR
    output wire                 init_done,
    output wire                 cal_ok,
    output wire [7:0]           cal_fail_code,
    output wire [31:0]          err_count
);
```

## Behaviour requirements

1. **`init_done` and `cal_ok` are separate signals.** Initialisation completing and
   calibration succeeding are different events with different recovery actions, and
   `I-02` needs to tell the supervisor which one failed.
2. **Calibration failure must be reported with a code, not just a flag.** A board
   that fails read calibration and a board with an unpopulated memory need different
   responses, and on a power-gated payload this happens on every wake-up.
3. **Responses may return out of order** if the controller reorders. Carry `cmd_id`
   through so `MEM-02` can match them. If the chosen configuration guarantees
   in-order responses, state that in the header and let `MEM-02` rely on it — but
   state it, rather than leaving it as an assumption somebody discovers later.
4. The wrapper is **plain Verilog**: no vendor primitives, no SystemVerilog
   interfaces, so `MEM-02` and above stay simulatable with a stub
   (`rtl/README.md` §7).
5. **Document the latency and the sustained bandwidth actually measured** in
   simulation, as the number `MEM-02` and `D-03` budget against. An estimate from the
   datasheet is a starting point, not a budget.
6. Refresh is the controller's business, but its **effect** is ours: refresh stalls
   are what `DP-05`'s depth has to absorb. Measure the worst-case stall and publish
   it — `DP-05` requirement 2 depends on this number.

## Acceptance criteria

- Write-then-read across the full address range (strided, not exhaustive) returns
  exactly what was written, through the wrapper, against the simulation model.
- Byte-masked writes modify exactly the masked bytes.
- Random read/write traffic against a Python reference memory model over at least
  10 000 transactions: every read matches.
- Out-of-order responses (if the configuration permits them) are matched correctly
  by `cmd_id`; a test deliberately returning them out of order.
- Calibration failure injected in the model: `cal_ok` low, `cal_fail_code` set,
  `I-02` sees the failure and reports it, no deadlock.
- **Measured and documented**: sustained read bandwidth, sustained write bandwidth,
  bandwidth with the mixed read/write pattern `D-03` chose, and worst-case
  refresh stall in `clk_sys` cycles. These numbers go in `docs/DDR_BRINGUP.md` and
  feed `MEM-02`, `DP-05` and `D-04`.
- `tools/dev synth` maps the real controller and reports its resource use; it is
  3–5k LUTs by itself (`rtl/RTL_PLAN.md` "Risks"), so this is the moment the
  device ceiling in `rtl/ecp5_target.yaml` gets its first real test.

## References

- `rtl/RTL_PLAN.md` §5, "Risks"
- `D-03` (layout, which determines the access pattern to benchmark)
- litedram: https://github.com/enjoy-digital/litedram
