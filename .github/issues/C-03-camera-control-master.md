---
id: C-03
title: "RTL: camera control UART master — command/response framing, timeouts, CSR pass-through"
labels: [rtl, P1, "area:control", "size:M"]
depends_on: [C-02, C-01, D-01]
---

## What

The block that turns a CSR write into a camera command and a camera reply into a
CSR-readable response. `UART_CAM` in `io_specs/fpga.yaml`.

## Why it matters more than its size suggests

The client was explicit: *"need to get reset controls of the camera and all other
controls of the camera that the ground station can have control of"*, and *"FPGA
tells the camera to start recording"*. This block is the entire path between the
ground station and the camera's own configuration. If it cannot report that a
command went unanswered, a camera that stopped responding looks identical to a
camera that is working fine — and the pass is wasted.

## Deliverables

- `rtl/fpga/cam_ctrl_master.v`
- `rtl_tests/common/utoss_tb/camera_uart.py` — a camera-side BFM that answers
  commands, and can be told to misbehave (see acceptance criteria)
- A bench
- `docs/FSM_CAM_CTRL.md` — the state diagram (the client asked for FSM diagrams)

## Interface

```verilog
module cam_ctrl_master #(
    parameter integer CMD_BYTES_MAX  = 16,
    parameter integer RESP_BYTES_MAX = 16,
    // Timeout in clk_sys cycles. MUST be longer than the camera's worst-case
    // response time -- which is a datasheet number from D-01, not a guess.
    parameter integer TIMEOUT_CYCLES = 100_000,
    parameter integer RETRIES        = 2
) (
    input  wire       clk_sys,
    input  wire       rst_sys_n,

    // From the CSR block (C-01)
    input  wire       cmd_start,
    input  wire [7:0] cmd_len,
    input  wire [7:0] cmd_byte,        // written repeatedly to fill the buffer
    input  wire       cmd_byte_valid,
    output wire       cmd_busy,

    output wire       resp_valid,
    output wire [7:0] resp_len,
    output wire [7:0] resp_byte,
    input  wire       resp_byte_next,

    output wire       err_timeout,      // sticky + counter
    output wire       err_bad_resp,     // sticky + counter
    output wire [7:0] timeout_count,    // saturating
    output wire [7:0] retry_count,      // saturating

    // To the UART core (C-02)
    output wire [7:0] uart_tx_tdata,
    output wire       uart_tx_tvalid,
    input  wire       uart_tx_tready,
    input  wire [7:0] uart_rx_tdata,
    input  wire       uart_rx_tvalid,
    output wire       uart_rx_tready
);
```

## Behaviour requirements

1. **The command framing is the camera's, and it is not known until `D-01`
   resolves.** Write this module so the frame format lives in one place —
   preferably a parameterized header/checksum/terminator scheme — and say in the
   module header which camera's protocol the current encoding assumes. Do not spread
   the format across the FSM.
2. **Every command has a timeout.** On expiry: retry up to `RETRIES`, then latch
   `err_timeout`, increment the saturating counter, and return to idle. Never wait
   forever. A payload stuck waiting for a camera that is not answering is a payload
   that reports nothing for the rest of the pass.
3. **A malformed or short response is an error, not a value.** Validate length and
   checksum; on failure latch `err_bad_resp` and do not present the bytes as a
   response. Half a response interpreted as a value is worse than no response.
4. **Flush stale bytes before a new command.** If a late reply to a timed-out
   command arrives after the retry, it must not be mistaken for the answer to the
   current one. This is the subtle bug in every request/response master, and it is
   the one that produces a confident wrong answer.
5. `cmd_busy` must prevent a second command from starting mid-transaction, and a
   `cmd_start` while busy must be reported rather than dropped.
6. **Camera reset/power control is a separate path.** If the camera's reset is a
   GPIO rather than a UART command, it does not belong in this FSM — put it in the
   CSR directly, with the sequencing requirement documented. Getting a camera out of
   a hung state must not depend on the UART that is hung.
7. `default:` arm returns to idle (`rtl/README.md` §4).

## Resource budget

Expect under 300 LUTs and 300 FFs, plus the command/response buffers. Set
`synth.budget` from a measured run.

## Acceptance criteria

The camera BFM must be able to misbehave on demand, and each of these is a test:

- **Happy path**: command out, well-formed response in, bytes readable at the CSR.
- **No response at all**: timeout fires after `TIMEOUT_CYCLES`, retries happen,
  `err_timeout` latches, `timeout_count` increments, FSM returns to idle.
- **Response one byte short**: `err_bad_resp` latches, no partial response is
  presented.
- **Bad checksum**: `err_bad_resp` latches.
- **Late response**: BFM answers *after* the timeout and retry have fired. The late
  bytes must not be attributed to the next command. Assert explicitly on the
  response contents of the following command.
- **Response arriving byte-at-a-time with long gaps** (slower than the camera's
  nominal rate but within the timeout): still assembled correctly.
- **Garbage on the line while idle**: discarded, does not start a response state.
- **Back-to-back commands**: second blocked while `cmd_busy`, and the attempt is
  reported.
- **Counters saturate** rather than wrap.
- `docs/FSM_CAM_CTRL.md` has the diagram, with every timeout and retry path.

## References

- `rtl/RTL_PLAN.md` §9
- `io_specs/fpga.yaml` (`UART_CAM`, 4 mA drive chosen deliberately)
- `UTAT Meeting.txt`: camera reset and ground-station control; "FPGA tells the
  camera to start recording"
