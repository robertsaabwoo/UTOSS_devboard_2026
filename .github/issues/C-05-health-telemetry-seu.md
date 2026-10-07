---
id: C-05
title: "RTL: health, telemetry and SEU mitigation (counters, heartbeat, config CRC scrub, TMR on critical FSMs)"
labels: [rtl, P1, "area:control", "size:L"]
depends_on: [C-01, I-02, D-05]
---

## What

Three related things that together answer "is the payload alive and should the
supervisor do something about it":

1. The error/telemetry counter aggregation feeding the CSR block.
2. A heartbeat the supervisor's watchdog can observe.
3. Configuration-memory scrubbing, and triple-modular redundancy on the FSMs where
   an upset is unrecoverable.

## Why SEU is in scope and not a later problem

`io_specs/fpga.yaml` `open_items/seu-mitigation`: the ECP5 is SRAM-configured, so
a single-event upset in configuration memory can silently corrupt the design — a
known hazard for SRAM FPGAs on orbit. Nothing about this is theoretical for a
satellite payload.

The supervisor is already wired for slave configuration
(`io_specs/supervisor.yaml`), so it is the natural place to force a reconfigure.
What we owe it is (a) a liveness signal it can trust and (b) early warning that
configuration memory has changed, so it can reconfigure *before* a corrupted
design writes a corrupted cube.

Note: whether scrubbing is **mandatory** is a mission-assurance question about the
radiation environment, not an electrical one. Settle that as part of this issue
rather than discovering it late — it constrains the supervisor firmware too.

## Deliverables

- `rtl/fpga/health_mon.v` — counter aggregation, saturation, heartbeat
- `rtl/fpga/cfg_crc_mon.v` — configuration readback/CRC monitor
- `rtl/fpga/tmr_fsm.v` — a reusable TMR wrapper for a state register
- Benches for each
- `docs/SEU_PLAN.md` — the radiation argument, what is protected, what is not, and
  why

## Interfaces

```verilog
module health_mon #(
    parameter integer N_COUNTERS = 16,
    parameter integer COUNTER_W  = 16,
    // Heartbeat period in clk_sys cycles. Must be well inside the supervisor's
    // watchdog timeout -- a number from the firmware, not a guess.
    parameter integer HEARTBEAT_DIV = 1_000_000
) (
    input  wire                         clk_sys,
    input  wire                         rst_sys_n,

    // One pulse per event, from everywhere in the design.
    input  wire [N_COUNTERS-1:0]        event_pulse,
    input  wire                         clear,          // from the CSR, w1c

    output wire [N_COUNTERS*COUNTER_W-1:0] counters,     // saturating
    output wire [N_COUNTERS-1:0]        sticky,

    // Liveness. See requirement 2 -- this must be able to STOP.
    input  wire                         pipeline_alive,
    output wire                         heartbeat
);

module tmr_fsm #(
    parameter integer WIDTH = 4
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire [WIDTH-1:0] next_state,
    output wire [WIDTH-1:0] state,            // majority vote of three copies
    output wire             mismatch          // sticky: a copy disagreed
);
```

## Behaviour requirements

1. **Every counter saturates, never wraps** (`D-05`). A wrapped counter reads zero
   after a storm of errors and is indistinguishable from a clean pass.
2. **The heartbeat must be able to stop.** A free-running divider off `clk_sys`
   toggles happily while the datapath is wedged, which makes the watchdog useless —
   it then only detects a dead clock, which is the one failure the supervisor can
   already see. Gate the heartbeat on evidence of forward progress (`pipeline_alive`:
   FSMs leaving states, counters advancing while a capture is active). Document
   exactly what "alive" means, because that definition *is* the watchdog's coverage.
3. `tmr_fsm` holds three copies of the state register and majority-votes them.
   `mismatch` latches when a copy disagreed — which is both the detection signal and
   the evidence that scrubbing is needed. **The three copies must survive
   synthesis**: yosys will happily merge identical registers and optimise your
   redundancy away. Add the appropriate `keep` attribute and *verify in the netlist*
   that three registers exist. Check this in the bench's synthesis step, not by
   inspection — it is silent when it fails.
4. Apply `tmr_fsm` to the FSMs where an upset is unrecoverable within a pass:
   `coldstart_fsm` (`I-02`), the capture FSM (`INT-01`), and the SD write FSM
   (`ST-01`). Not to everything — TMR triples area, and the compressor datapath is
   better protected by detecting a bad output than by tripling the predictor.
5. `cfg_crc_mon` periodically reads back configuration memory and compares a CRC
   against the expected value, reporting a mismatch to the supervisor. Decide and
   document whether readback is done by us over the ECP5's own readback path or by
   the supervisor over its configuration interface — the second is less RTL and the
   supervisor already owns that path, which probably makes it the right answer.
6. **Scrubbing must not corrupt a capture in progress.** Either inhibit it during a
   capture, or prove the readback path cannot disturb the running design. State which.

## Resource budget

`health_mon` scales with `N_COUNTERS * COUNTER_W`; expect ~400 LUTs and ~300 FFs at
the defaults. `tmr_fsm` triples whatever it wraps — account for it in the budget of
each module that uses it, not here. Keep the total in view against
`utilization_ceiling` in `rtl/ecp5_target.yaml`.

## Acceptance criteria

- Every counter driven past its maximum: saturates, does not wrap.
- `clear` from the CSR clears exactly the counters written and no others.
- **Heartbeat stops** when `pipeline_alive` stops, within a bounded number of
  cycles. This is the test that proves the watchdog has coverage; a bench that only
  checks the heartbeat toggles proves nothing.
- `tmr_fsm`: force each copy to a wrong value in turn — the majority vote holds,
  `mismatch` latches. Force two copies wrong — the vote follows the majority, which
  is now wrong, and the bench asserts `mismatch` is still set. (Double-upset is not
  correctable; it must at least be *reported*.)
- **A synthesis check asserting three state registers exist** in the mapped netlist
  for a `tmr_fsm` instance. Parse `build/synth/.../*.json` or the yosys log; do not
  rely on reading the source.
- `cfg_crc_mon`: injected CRC mismatch is reported; no mismatch is reported during
  normal operation across a long run.
- `docs/SEU_PLAN.md` states the expected orbit and radiation environment, the
  expected upset rate for this part, what is protected, what is not, and why that
  split is acceptable.

## References

- `rtl/RTL_PLAN.md` §14
- `io_specs/fpga.yaml` `open_items/seu-mitigation`
- `io_specs/supervisor.yaml` (slave configuration, `PROGRAMN`)
