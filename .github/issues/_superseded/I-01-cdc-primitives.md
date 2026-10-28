---
id: I-01
title: "RTL: CDC and FIFO primitive library (sync_2ff, reset_sync, pulse_cdc, fifo_sync, fifo_async)"
labels: [rtl, P0, "area:infrastructure", "size:M", good-first-issue]
depends_on: []
---

## What

The five building blocks every other module in the design uses. Write them once,
correctly, with benches that would actually catch a broken one.

**Start here.** Almost everything else depends on these, and they are the best
possible introduction to the repo's conventions and test flow.

## Why one library and not five hand-rolled copies

At least four clock domains are in play (camera pixel, DDR, system, SD —
`rtl/ecp5_target.yaml` `clock_domains`). A hand-rolled synchronizer per crossing
is a separate place for a metastability bug to hide, and the failure mode is a
payload that works on the bench and corrupts one cube in fifty on orbit. There is
no way to debug that from telemetry.

## Deliverables

| File | Module |
|---|---|
| `rtl/fpga/common/sync_2ff.v` | two-flop synchronizer for a **single-bit** signal |
| `rtl/fpga/common/reset_sync.v` | async-assert / sync-release reset synchronizer |
| `rtl/fpga/common/pulse_cdc.v` | single-cycle pulse from one domain to another |
| `rtl/fpga/common/fifo_sync.v` | single-clock FIFO |
| `rtl/fpga/common/fifo_async.v` | dual-clock FIFO, gray-coded pointers |

Plus a bench directory per module under `rtl_tests/fpga/`.

## Interfaces

```verilog
// Two-flop synchronizer. SINGLE BIT ONLY -- see requirement 1.
module sync_2ff #(
    parameter integer STAGES   = 2,      // 3 where the MTBF budget demands it
    parameter         RESET_VAL = 1'b0
) (
    input  wire clk_dst,
    input  wire rst_dst_n,
    input  wire d_src,
    output wire q_dst
);

// Asynchronous assert, synchronous release.
module reset_sync #(
    parameter integer STAGES = 3
) (
    input  wire clk_dst,
    input  wire rst_async_n,   // may be asserted at any time
    output wire rst_dst_n      // deasserts synchronously to clk_dst
);

// One pulse in clk_src becomes exactly one pulse in clk_dst.
module pulse_cdc (
    input  wire clk_src,
    input  wire rst_src_n,
    input  wire pulse_src,
    output wire busy_src,      // a new pulse while busy would be lost
    input  wire clk_dst,
    input  wire rst_dst_n,
    output wire pulse_dst
);

module fifo_sync #(
    parameter integer WIDTH = 16,
    parameter integer DEPTH = 16       // need not be a power of two
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              wr_en,
    input  wire [WIDTH-1:0]  wr_data,
    output wire              full,
    input  wire              rd_en,
    output wire [WIDTH-1:0]  rd_data,
    output wire              empty,
    output wire [$clog2(DEPTH+1)-1:0] level,
    output wire [$clog2(DEPTH+1)-1:0] high_water,   // peak level since reset
    output wire              overflow,              // sticky: wr_en while full
    output wire              underflow              // sticky: rd_en while empty
);

module fifo_async #(
    parameter integer WIDTH = 16,
    parameter integer DEPTH = 16        // MUST be a power of two
) (
    input  wire              clk_wr,
    input  wire              rst_wr_n,
    input  wire              wr_en,
    input  wire [WIDTH-1:0]  wr_data,
    output wire              full,
    output wire [$clog2(DEPTH+1)-1:0] wr_level,     // conservative
    output wire              overflow,              // sticky, in clk_wr

    input  wire              clk_rd,
    input  wire              rst_rd_n,
    input  wire              rd_en,
    output wire [WIDTH-1:0]  rd_data,
    output wire              empty,
    output wire [$clog2(DEPTH+1)-1:0] rd_level,     // conservative
    output wire              underflow              // sticky, in clk_rd
);
```

## Behaviour requirements

1. **`sync_2ff` carries one bit.** If a future caller needs a bus, it must use
   `fifo_async` or a handshake around a held value — not *N* parallel
   synchronizers, which resolve independently and can present a word that was
   never written. Say this in the module header so nobody has to rediscover it.
2. `reset_sync` deasserts synchronously and asserts asynchronously. The
   asynchronous path must not be registered.
3. `pulse_cdc` must not drop or duplicate a pulse. It must report `busy_src` so a
   caller can see when it is pushing pulses faster than the destination domain can
   take them, rather than losing them silently.
4. `fifo_async` pointers are **gray-coded** and crossed with `sync_2ff`. Nothing
   else crosses between the two domains.
5. `full` and `empty` are never wrong in the unsafe direction. `full` may assert
   pessimistically (earlier than strictly necessary); it may never fail to assert
   when the FIFO is actually full. Same for `empty` in the other direction. Level
   outputs are conservative on each side: `wr_level` may read high, `rd_level` may
   read low.
6. **`overflow` and `underflow` are sticky** and stay set until reset. A
   transient overflow pulse that nobody was watching is an overflow that did not
   get reported, and these feed the CSR error counters (`D-05`).
7. `high_water` tracks the peak level since reset and feeds the CSR high-water
   marks. This is how we find out a FIFO was nearly full on orbit without having
   overflowed yet.
8. No logic on a clock, no gated clocks, no latches, no `initial` blocks for reset
   state. `rtl/README.md` §3, §4.
9. `fifo_sync` must infer EBR when `WIDTH*DEPTH` is large enough to warrant it,
   and distributed logic when it is small. Check which one you got with
   `tools/dev synth`; a small FIFO that lands in an EBR wastes a scarce resource,
   and a large one that lands in LUTs is how a 2 kB buffer becomes 16 000 LUTs.

## Resource budget

Set each `synth.budget` from a first measured run. Rough expectation at
`WIDTH=16, DEPTH=16`: `sync_2ff` and `reset_sync` under 10 FFs, `pulse_cdc` under
20, `fifo_sync` under 100 LUTs, `fifo_async` under 200 LUTs.

## Acceptance criteria

Each module needs a bench under `rtl_tests/fpga/<name>/` with at least the
parameter sets listed, and the following cases. These are the tests — a bench
without them does not close this issue.

**`fifo_sync`** (`WIDTH` 1/8/32, `DEPTH` 2/16/1024 — include a non-power-of-two
depth such as 7):
- fill to exactly `DEPTH`, confirm `full`, confirm `level == DEPTH`
- write while full: data is dropped, existing contents are **unchanged**,
  `overflow` latches
- read while empty: `underflow` latches, `rd_data` behaviour is defined
- simultaneous read and write at every occupancy from 0 to `DEPTH`, which is
  where the classic off-by-one lives
- random traffic with a reference model (a Python `deque`) over at least
  100 000 cycles, comparing every beat
- `high_water` equals the true peak across the run
- reset mid-traffic empties the FIFO and clears the sticky flags

**`fifo_async`** (`WIDTH` 1/14/32, `DEPTH` 4/1024; clock ratios 1:1, 1:7, 7:1,
and two clocks with no integer relationship such as 100 MHz and 37.3 MHz):
- the reference-model comparison above, across every clock ratio
- write-side burst into a stalled read side until `full`, then drain: no loss, no
  duplication, no reordering
- `overflow` latches on the write side only, `underflow` on the read side only
- independent asynchronous resets: reset each side separately while the other is
  active, and confirm the FIFO recovers to a consistent empty state. This is the
  case that hand-rolled async FIFOs usually get wrong.

**`pulse_cdc`** (clock ratios 1:1, 1:10, 10:1):
- one pulse in, exactly one pulse out, at every ratio
- back-to-back pulses faster than the destination can accept: `busy_src` asserts,
  and the bench asserts that no pulse is **silently** lost (it is either accepted
  or refused while busy)
- a pulse arriving during destination reset does not produce a spurious output

**`sync_2ff`** / **`reset_sync`**:
- a change on the input appears after exactly `STAGES` destination edges
- `reset_sync` asserts within one destination cycle of `rst_async_n` falling
  regardless of clock phase, and deasserts synchronously
- both hold their reset value while reset is asserted

## References

- `rtl/RTL_PLAN.md` §13, §3
- `rtl/README.md` §3, §6
- `rtl/ecp5_target.yaml` `clock_domains`
