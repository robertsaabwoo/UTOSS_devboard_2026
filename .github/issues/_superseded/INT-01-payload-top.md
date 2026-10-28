---
id: INT-01
title: "RTL: payload_top integration, capture FSM, and the FSM diagram set for the client"
labels: [rtl, P1, "area:integration", "size:L"]
depends_on: [C-01, I-02, DP-05, MEM-03, CMP-03, ST-01]
---

## What

The top-level module that instantiates everything, plus the capture FSM that
sequences a pass: idle → camera configured → capturing → compressing → offloading →
idle. And the diagram set the client asked for.

## Why it is a real piece of work and not a wiring exercise

Every module in this design was verified in isolation against a bench that gave it
well-behaved neighbours. Integration is where the assumptions meet: the arbiter's
worst-case latency against the CDC FIFO's depth, the compressor's throughput against
the camera's rate, the SD card's busy periods against the buffering. Those are the
numbers each issue was asked to measure and publish, and this is where they are
checked against each other.

It is also where the client's explicit asks land: *"they want an FSM diagram"* and
*"will need an image of the CPU and FPGA for startup"*.

## Deliverables

- `rtl/fpga/payload_top.v`
- `rtl/fpga/capture_fsm.v`
- A top-level bench with `synth.place: true` (see `I-03`)
- `docs/FSM_CAPTURE.md` — the capture state diagram
- `docs/ARCHITECTURE.md` — the block diagram with every clock domain, every CDC and
  every arbiter port marked
- `docs/BRINGUP.md` — the supervisor's view: what it must do, in what order, to take
  a capture, and what every status and error register means. This is the companion to
  `docs/CSR_MAP.md` from `D-05` and together they are the payload's interface document.

## Capture FSM

```verilog
module capture_fsm (
    input  wire       clk_sys,
    input  wire       rst_sys_n,

    // From the CSR (C-01)
    input  wire       cmd_start,
    input  wire       cmd_stop,
    input  wire       cmd_abort,

    // From the subsystems
    input  wire       payload_ready,      // I-02
    input  wire       cam_cfg_done,       // C-03
    input  wire       frame_done,         // DP-04
    input  wire       compress_done,      // CMP-03
    input  wire       offload_done,       // ST-01
    input  wire       any_fatal_error,

    // Control out
    output wire       cam_enable,
    output wire       capture_enable,
    output wire       compress_enable,
    output wire       offload_start,

    output wire [3:0] state,              // to the CSR
    output wire [7:0] abort_code,
    output wire       pipeline_alive      // to C-05 heartbeat gating
);
```

## Behaviour requirements

1. **One owner per control signal.** Every `*_enable` is driven from exactly here.
   Two blocks able to start a capture is two blocks that will disagree about whether
   one is running.
2. **Abort must be safe at every point in the sequence**, and must leave the card and
   the DDR buffer in a state where the **next** capture works. An abort that half-writes
   an index (`ST-01` requirement 6) or leaves the ring pointers inconsistent
   (`MEM-03`) breaks every subsequent pass, which is far worse than one lost capture.
3. **Any fatal error aborts with a distinct `abort_code`** and holds it for the CSR.
   The supervisor's choice between "retry" and "power-cycle" depends on knowing which
   stage failed.
4. **`pipeline_alive` must be real evidence of forward progress**, not a timer —
   see `C-05` requirement 2. It is what gives the supervisor's watchdog any coverage at
   all, and getting it wrong makes the watchdog decorative.
5. **No stage may start before its predecessor's data is complete.** In particular
   compression must not start on a frame still being written, and offload must not start
   on a cube still being compressed. State the handshake for each, and make the bench
   check it rather than relying on timing.
6. **The whole-design worst-case arithmetic must be written down in
   `docs/ARCHITECTURE.md`**, using the numbers the other issues measured: camera pixel
   rate, `MEM-02` worst-case latency per port, `DP-05` FIFO depth, compressor
   throughput, `ST-01` sustained rate and worst busy period. Then show the margin at
   each stage. Where a margin is negative, that is a finding — raise it rather than
   hoping the bench does not catch it.
7. `default:` arm; TMR per `C-05`.

## Acceptance criteria

- **Full-chain capture in simulation**: synthetic cube from the camera model, through
  every block, to the SD card model. Read the card image back, parse it with the
  `CMP-04` Python parser, decompress with `V-01`, and compare bit-exactly to the input
  cube. This is `V-03`, and it is the test that says the payload works.
- `tools/dev synth --only payload_top` runs yosys **and** nextpnr with `I-03`'s
  constraints, and meets timing on every clock domain. The resource report must be
  within `utilization_ceiling` in `rtl/ecp5_target.yaml`.
- A capture started before `payload_ready` is refused, with the reason in the CSR.
- **Abort at every state** in the FSM, each followed by a **complete successful
  capture**. The second capture is the real test; an abort that leaves state behind
  passes the first half of this.
- Fatal error injected at each stage: distinct `abort_code`, clean stop, CSR readable,
  next capture works.
- `pipeline_alive` deasserts when any stage stops making progress, verified by stalling
  each stage in turn.
- Every FIFO and arbiter telemetry counter is reachable over the CSR and reads
  plausibly after a full capture.
- Three diagrams committed: cold start (`I-02`), capture (here), camera control
  (`C-03`). Plus `docs/ARCHITECTURE.md` with the worst-case arithmetic from
  requirement 6.
- `docs/BRINGUP.md` is complete enough that the supervisor firmware can be written
  from it without asking us anything.

## References

- `rtl/RTL_PLAN.md` — all sections
- `UTAT Meeting.txt`: "they want an FSM diagram"; "will need an image of the CPU and
  FPGA for startup"; "In January, we should have our Verilog and PCB layout done"
- `D-05` (`docs/CSR_MAP.md`), `I-03` (constraints), `V-03` (full-chain bench)
