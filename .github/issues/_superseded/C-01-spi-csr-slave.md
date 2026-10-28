---
id: C-01
title: "RTL: supervisor register interface — SPI slave + CSR block (replaces reg_handshake placeholder)"
labels: [rtl, P0, "area:control", "size:M"]
depends_on: [D-05, I-01]
---

## What

The memory-mapped control and status interface the supervisor CPU talks to.
STM32-class master, FPGA slave, SPI. This is the module `rtl/fpga/reg_handshake.v`
is a placeholder for; delete the placeholder and its bench as part of this work.

## Why SPI slave

Per `rtl/RTL_PLAN.md` §10: the supervisor is the master, SPI is fast enough and
simple, and the supervisor already owns an SPI-shaped relationship with the FPGA
for slave configuration. The alternative (a UART command protocol) costs the
supervisor a second interface and costs us a parser.

## Deliverables

- `rtl/fpga/spi_slave.v` — the SPI shift register and transaction framing, in the
  SPI clock domain
- `rtl/fpga/csr_regfile.v` — the register file in `clk_sys`, generated against
  `rtl/fpga/csr_map.yaml` (`D-05`)
- `rtl/fpga/csr_block.v` — the two plus the CDC between them
- Benches for each, plus an SPI master BFM in `rtl_tests/common/utoss_tb/spi.py`
- `rtl/fpga/reg_handshake.v` and `rtl_tests/fpga/reg_handshake/` **deleted**

## Interfaces

```verilog
module spi_slave #(
    parameter integer ADDR_W = 8,
    parameter integer DATA_W = 32
) (
    // SPI pins -- asynchronous to everything
    input  wire                 sclk,
    input  wire                 cs_n,
    input  wire                 mosi,
    output wire                 miso,
    output wire                 miso_oe,     // drive MISO only while selected

    input  wire                 clk_sys,
    input  wire                 rst_sys_n,

    // Register access, in clk_sys
    output wire                 req_valid,
    output wire                 req_write,
    output wire [ADDR_W-1:0]    req_addr,
    output wire [DATA_W-1:0]    req_wdata,
    input  wire                 req_ready,
    input  wire [DATA_W-1:0]    req_rdata,
    input  wire                 req_rvalid,

    output wire                 err_short_frame,   // sticky
    output wire                 err_overrun        // sticky
);

module csr_regfile #(
    parameter integer ADDR_W = 8,
    parameter integer DATA_W = 32
) (
    input  wire              clk_sys,
    input  wire              rst_sys_n,

    input  wire              req_valid,
    input  wire              req_write,
    input  wire [ADDR_W-1:0] req_addr,
    input  wire [DATA_W-1:0] req_wdata,
    output wire              req_ready,
    output wire [DATA_W-1:0] req_rdata,
    output wire              req_rvalid,
    output wire              err_bad_addr,      // sticky

    // Control out / status in: one port group per CSR group in csr_map.yaml.
    // Generated from the YAML -- do not hand-write this list.
    output wire              ctrl_capture_start,
    output wire              ctrl_capture_stop,
    output wire              ctrl_soft_reset,
    // ... see rtl/fpga/csr_map.yaml
    input  wire [31:0]       stat_frames,
    input  wire [31:0]       stat_fifo_overflows
    // ...
);
```

## Behaviour requirements

1. **Frame format**: define it explicitly in the module header — command byte
   (read/write plus address), then data, MSB first, on which SCLK edge, with which
   CPOL/CPHA. Then make the bench enforce exactly that. An SPI interface whose
   edge convention lives only in the implementation is one the firmware team will
   get wrong once and then not trust again.
2. **`cs_n` deasserting mid-transaction aborts it.** No partial write is
   committed. A truncated write that lands half a register is worse than a
   rejected one, because nothing reports it. `err_short_frame` latches.
3. **MISO is tri-stated when `cs_n` is high** (`miso_oe`). The supervisor may share
   the bus.
4. **Writes are atomic from the supervisor's point of view.** A multi-byte write
   takes effect as one register write at the end of the frame, not byte by byte as
   it shifts in. A capture that starts because the start bit arrived before the
   mode bits is a real failure mode.
5. **Reads of a multi-word counter are atomic.** Per `D-05`: latch the full value
   when the low word is read, or provide a snapshot bit. Reading two halves that
   moved in between produces a number that was never true.
6. **Every error counter saturates, never wraps** (`D-05`). A wrapped counter
   reads zero after a storm, which is indistinguishable from a clean pass.
7. **CDC**: the SPI domain and `clk_sys` are asynchronous. Cross with `I-01`
   primitives only — `pulse_cdc` for the request, a held value plus handshake for
   the payload. No multi-bit bus through parallel `sync_2ff`. Do not assume SCLK is
   slower than `clk_sys`; constrain it, state the assumption in the header, and
   have the bench violate it to prove the FIFO/handshake holds.
8. **An unmapped address must not hang the bus.** It completes, returns a defined
   value (zero), and latches `err_bad_addr`. A master that can hang the payload by
   reading the wrong address is a master that will.
9. Reserved fields read zero and ignore writes, so the map can grow (`D-05`).
10. `csr_regfile` is **generated** from `rtl/fpga/csr_map.yaml` by
    `scripts/gen_csr.py` (`D-05`), not hand-written. CI checks it is in sync.

## Resource budget

Expect 400–800 LUTs and 600+ FFs, dominated by the register file itself, growing
with the register count. Set `synth.budget` from a measured run and revisit it
when registers are added.

## Acceptance criteria

- SPI master BFM in `rtl_tests/common/utoss_tb/spi.py`, reusable by other benches.
- Write-then-read round-trip on every `rw` register in `csr_map.yaml`, driven from
  the YAML so a new register is covered automatically rather than when somebody
  remembers.
- `ro` registers reject writes; `w1c` bits clear only the bits written.
- `cs_n` deasserted at every bit position within a write frame: no partial commit,
  `err_short_frame` latches.
- Read of an unmapped address: returns zero, latches `err_bad_addr`, bus still
  usable afterwards.
- Multi-word counter read while the counter is incrementing every cycle: the two
  halves are consistent with a single instant.
- Error counter driven past its maximum: saturates, does not wrap.
- SCLK at 1/20, 1/2 and **1.5x** `clk_sys` frequency: all pass, or the
  out-of-range case is explicitly rejected by the design rather than silently
  corrupting.
- Soft reset over the CSR resets the datapath but **not** the CSR block itself —
  otherwise the supervisor loses the error state that told it to reset.
- `tools/dev all` green; `reg_handshake` and its bench are gone and `tools/dev list`
  no longer shows it.

## References

- `rtl/RTL_PLAN.md` §10
- `D-05` (`rtl/fpga/csr_map.yaml`)
- `io_specs/supervisor.yaml`
- `UTAT Meeting.txt`: "They expect us to provide them the tools to talk to the CPU"
