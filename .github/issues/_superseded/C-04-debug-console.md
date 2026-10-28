---
id: C-04
title: "RTL: debug console UART (CONSOLE_TX) with optional command parser"
labels: [rtl, P2, "area:control", "size:S", good-first-issue]
depends_on: [C-02]
---

## What

A ground-support-only console on `CONSOLE_TX`. TX at minimum: a readable stream
of what the payload is doing during bring-up, without needing the supervisor in
the loop.

## Why it is P2 but still worth doing

The supervisor CSR path (`C-01`) covers almost all of this, and the console is
explicitly ground-support only (`io_specs/uart_io.yaml`) — it is not part of the
flight data path. But during board bring-up the supervisor is often the thing that
is broken, and a console that prints "sys PLL locked / DDR cal failed" into a
terminal is worth a great deal at 2 a.m. in MY618.

Keep it small. A console that grows into a second control interface is a second
control interface to verify.

## Deliverables

- `rtl/fpga/console_tx.v` — formatter plus TX FIFO over `uart_tx` from `C-02`
- Optionally `rtl/fpga/console_parser.v` — a minimal RX command parser
- A bench

## Interface

```verilog
module console_tx #(
    parameter integer CLK_HZ    = 100_000_000,
    parameter integer BAUD      = 115200,
    parameter integer FIFO_DEPTH = 256
) (
    input  wire       clk_sys,
    input  wire       rst_sys_n,

    // Byte stream in, from wherever in the design wants to say something.
    input  wire [7:0] msg_tdata,
    input  wire       msg_tvalid,
    output wire       msg_tready,

    // Event pulses the module renders as fixed strings itself, so a block that
    // wants to report something does not have to own a string buffer.
    input  wire [7:0] event_id,
    input  wire       event_valid,

    output wire       console_txd,
    output wire       fifo_overflow,     // sticky -- see requirement 2
    output wire [8:0] fifo_high_water
);
```

## Behaviour requirements

1. **The console must never apply backpressure to the datapath.** If the FIFO is
   full, drop the message and latch `fifo_overflow`. A debug print that stalls a
   pixel pipeline is a debug print that corrupts a capture — this is the single most
   important rule in this module.
2. `fifo_overflow` is sticky and reported over the CSR, so dropped output is
   visible rather than mysterious.
3. Event rendering (`event_id` → a fixed string) is a lookup table, in one place.
   Keep the table in sync with an enum in `docs/CONSOLE_EVENTS.md` so the strings
   mean the same thing to the person reading the terminal.
4. If a parser is included: it accepts a **read-only** command set only — dump
   status, dump counters, print the register map. **No command may change payload
   state.** There are then two paths that can start a capture, and the console is the
   one with no authentication and a header anybody can clip onto. Write this
   restriction in the module header.
5. 8-N-1, baud parameterized, using `C-02`. No new UART implementation.

## Resource budget

Under 200 LUTs plus the FIFO (which should land in an EBR at `FIFO_DEPTH=256`,
`WIDTH=8` — check with `tools/dev synth`, since a 2 kbit buffer in LUTs costs
roughly a hundred times its fair price).

## Acceptance criteria

- Byte stream in appears on `console_txd` at the configured baud, verified by
  decoding it with the `C-02` UART BFM.
- **FIFO full**: `msg_tready` stays **high** (messages are dropped, not stalled),
  `fifo_overflow` latches. Assert that no upstream stall occurs — this is
  requirement 1 and it is the test that matters.
- `fifo_high_water` matches the true peak.
- Every `event_id` renders its expected string.
- If a parser is built: every command is exercised, and a test asserts that no
  CSR control bit changes as a result of any console input.

## References

- `rtl/RTL_PLAN.md` §11
- `io_specs/uart_io.yaml`, `io_specs/fpga.yaml` (`CONSOLE_TX`)
