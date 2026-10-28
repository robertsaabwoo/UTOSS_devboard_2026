---
id: C-02
title: "RTL: parameterized UART core (uart_tx, uart_rx, baud generator)"
labels: [rtl, P1, "area:control", "size:S", good-first-issue]
depends_on: [I-01]
---

## What

A plain, parameterized 8-N-1 UART, used by both the camera control master
(`C-03`) and the debug console (`C-04`).

Small, self-contained, with no dependencies beyond the FIFO from `I-01`. A good
second issue after `I-01`.

## Deliverables

- `rtl/fpga/common/uart_baud.v`
- `rtl/fpga/common/uart_tx.v`
- `rtl/fpga/common/uart_rx.v`
- `rtl/fpga/common/uart_core.v` — the three together with optional FIFOs
- A bench per module, plus a UART BFM in `rtl_tests/common/utoss_tb/uart.py`

## Interfaces

```verilog
// Fractional-accumulator baud generator: an integer divider cannot hit common
// baud rates exactly from a 100 MHz clock, and the residual error accumulates
// across a frame until the stop bit is sampled in the wrong place.
module uart_baud #(
    parameter integer CLK_HZ   = 100_000_000,
    parameter integer BAUD     = 115200,
    parameter integer OVERSAMPLE = 16          // rx samples per bit
) (
    input  wire clk,
    input  wire rst_n,
    output wire tick_bit,       // one pulse per bit period (tx)
    output wire tick_sample     // OVERSAMPLE pulses per bit period (rx)
);

module uart_tx #(
    parameter integer DATA_BITS = 8,
    parameter integer STOP_BITS = 1
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tick_bit,
    input  wire [DATA_BITS-1:0] tx_tdata,
    input  wire       tx_tvalid,
    output wire       tx_tready,
    output wire       txd,
    output wire       busy
);

module uart_rx #(
    parameter integer DATA_BITS  = 8,
    parameter integer STOP_BITS  = 1,
    parameter integer OVERSAMPLE = 16
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tick_sample,
    input  wire       rxd,                 // asynchronous -- synchronize it
    output wire [DATA_BITS-1:0] rx_tdata,
    output wire       rx_tvalid,
    input  wire       rx_tready,
    output wire       err_framing,         // sticky: stop bit not high
    output wire       err_overrun,         // sticky: byte arrived, sink not ready
    output wire       err_break            // sticky: line held low a full frame
);
```

## Behaviour requirements

1. **`rxd` is asynchronous.** Synchronize it with `sync_2ff` from `I-01` before
   anything samples it. A UART receiver that samples a raw pad is a UART receiver
   that occasionally invents a start bit.
2. **Start-bit validation**: on a falling edge, re-sample at the middle of the
   start bit and reject it if it is no longer low. Otherwise a single noise glitch
   on an idle line produces a spurious byte, and on the camera control path a
   spurious byte is a spurious command.
3. **Sample each data bit at its centre**, using `OVERSAMPLE`. Majority-vote over
   three mid-bit samples if `OVERSAMPLE >= 8`; say in the header which you did.
4. **Framing, overrun and break errors are reported and sticky**, feeding CSR
   counters (`D-05`). A UART that silently drops a malformed byte gives the ground
   team no way to tell a broken cable from a camera that is not answering.
5. The baud generator must hit the requested rate within **±1 %** at every
   supported `CLK_HZ`/`BAUD` combination, and the bench must measure that rather
   than assume it. ±2 % is where the stop bit starts landing in the wrong place at
   8-N-1.
6. Stream ports follow the repo convention (`rtl/README.md` §5), so a FIFO from
   `I-01` drops straight in.
7. `uart_core` exposes optional TX and RX FIFOs with depth parameters, using
   `fifo_sync` — including its `high_water` and `overflow` outputs, which go to the
   CSR.

## Resource budget

Expect under 150 LUTs and 150 FFs for `uart_core` without FIFOs. Set
`synth.budget` from a measured run.

## Acceptance criteria

Parameter sets: `BAUD` 9600 / 115200 / 1000000, `CLK_HZ` 100 MHz (and one awkward
value such as 48 MHz where no integer divider is exact), `DATA_BITS` 7/8/9,
`STOP_BITS` 1/2.

- **Loopback**: `uart_tx` into `uart_rx` across every parameter set, 10 000 random
  bytes, zero errors, byte-for-byte match.
- **Measured baud**: the bench times the bit period on `txd` and asserts it is
  within ±1 % of the requested rate, at every `CLK_HZ`/`BAUD` pair. This is the
  test that catches a truncating integer divider.
- **Baud mismatch**: drive `uart_rx` from a BFM running 3 % fast and 3 % slow. One
  must still receive correctly (that is the point of mid-bit sampling); beyond that,
  errors must be *reported*, never silently wrong data.
- **Glitch rejection**: a 1-sample low pulse on an idle line produces no byte and
  no error.
- **Framing error**: BFM sends a frame with the stop bit low — `err_framing`
  latches, and the receiver resynchronizes on the next valid frame rather than
  jamming.
- **Overrun**: hold `rx_tready` low across two incoming bytes — `err_overrun`
  latches, and the receiver recovers.
- **Break**: line held low for more than a full frame — `err_break` latches, and
  releasing the line returns the receiver to idle.
- **Backpressure**: `tx_tvalid`/`tx_tready` and `rx_tvalid`/`rx_tready` checked
  with `check_stream_protocol`, with randomized backpressure on both.

## References

- `rtl/RTL_PLAN.md` §9, §11
- `io_specs/fpga.yaml` (`UART_CAM`, `CONSOLE_TX`), `io_specs/uart_io.yaml`
- `rtl/README.md` §5
