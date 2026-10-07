---
id: DP-05
title: "RTL: input CDC FIFO, camera pixel clock to system clock, with overflow telemetry"
labels: [rtl, P0, "area:datapath", "size:S"]
depends_on: [I-01, DP-04]
---

## What

The crossing from the camera's pixel clock domain into `clk_sys`. A thin wrapper
around `fifo_async` from `I-01`, carrying the sample plus its coordinates, with the
telemetry the mission actually needs.

## Why it is a separate issue from `I-01`

Because the requirement that makes it valuable is a payload requirement, not a FIFO
requirement: **it must expose an overflow counter.** From `rtl/RTL_PLAN.md` §3 —
knowing that a cube dropped pixels is far more useful than silently corrupting a
capture that cannot be re-taken. The imaging window is one to two minutes a day. A
cube with a hole in it that nobody knows about is worse than a cube that is marked
bad.

The other reason it is separate: the camera **cannot be backpressured**. It clocks
pixels out whether or not we are ready. So this FIFO is the only thing between a
transient downstream stall and permanent data loss, and its depth is a design
decision with a number behind it.

## Interface

```verilog
module pixel_cdc_fifo #(
    parameter integer SAMPLE_W = 16,
    parameter integer COORD_W  = 16,
    // Depth must be justified: see requirement 2.
    parameter integer DEPTH    = 1024
) (
    // Write side: camera pixel clock
    input  wire                 clk_px,
    input  wire                 rst_px_n,
    input  wire [SAMPLE_W-1:0]  wr_tdata,
    input  wire [COORD_W-1:0]   wr_x,
    input  wire [COORD_W-1:0]   wr_y,
    input  wire [COORD_W-1:0]   wr_band,
    input  wire                 wr_tvalid,
    input  wire                 wr_tlast,
    output wire                 wr_tready,

    // Read side: system clock
    input  wire                 clk_sys,
    input  wire                 rst_sys_n,
    output wire [SAMPLE_W-1:0]  rd_tdata,
    output wire [COORD_W-1:0]   rd_x,
    output wire [COORD_W-1:0]   rd_y,
    output wire [COORD_W-1:0]   rd_band,
    output wire                 rd_tvalid,
    output wire                 rd_tlast,
    input  wire                 rd_tready,

    // Telemetry. THE POINT OF THIS MODULE.
    output wire [31:0]          overflow_count,    // saturating, in clk_px
    output wire                 overflow_sticky,
    output wire [15:0]          high_water,        // peak occupancy
    output wire [15:0]          level_sys          // for live monitoring
);
```

## Behaviour requirements

1. Built on `fifo_async` (`I-01`). The sample and all three coordinates travel
   **through the same FIFO word**, so they cannot be separated. Do not cross them on
   separate paths; a sample that arrives with the previous sample's coordinates
   produces a cube that is scrambled in a way nothing downstream can detect.
2. **`DEPTH` must be justified with arithmetic, in the module header.** It has to
   absorb the worst-case downstream stall — primarily a DDR3 refresh plus arbitration
   latency while the camera keeps clocking (`MEM-02`). Write the calculation down:
   worst-case stall in `clk_sys` cycles, times the pixel rate, equals the minimum
   depth. A depth chosen because it looked round is a depth that will be found
   wanting on orbit.
3. **`overflow_count` saturates, never wraps**, and counts **samples lost**, not
   overflow events. A burst that loses 10 000 samples and a glitch that loses one
   must not read the same. It increments in `clk_px` and crosses to `clk_sys` for the
   CSR via the handshake in `I-01` — not via parallel `sync_2ff`.
4. **`overflow_sticky` latches and stays set until reset.** The CSR read may happen
   long after the burst. This bit is the one thing that tells the ground team whether
   to trust the cube.
5. **`high_water` tracks peak occupancy.** This is how we discover, before an
   overflow ever happens, that the margin is nearly gone — on a payload where the
   first real overflow is a lost capture, that early warning is the whole value.
6. `wr_tready` exists for protocol compliance, but the write side is expected to
   ignore it (the camera cannot be stalled). Say so in the header, and have the
   bench check that ignoring it produces counted loss rather than corruption.
7. Independent resets per side (`fifo_async` requirement from `I-01`): a `clk_px`
   reset when the camera powers down must not corrupt the read side or lose the
   telemetry.

## Resource budget

`DEPTH=1024` at `SAMPLE_W + 3*COORD_W = 64` bits is 64 kbit — about 4 EBRs on the
45F (18 kbit each). That is a real fraction of a scarce resource, so requirement 2
matters: check the mapping with `tools/dev synth` and confirm it lands in EBR rather
than LUTs. Expect under 200 LUTs of control logic.

Consider whether the coordinates need to cross at full width, or whether a
start-of-line marker plus a counter on the read side is enough. That trade is worth
2–3 EBRs and is the kind of thing to settle here rather than after `MEM-03` is
written against the wide interface.

## Acceptance criteria

Parameter sets: `DEPTH` 16/1024; clock ratios `clk_px` slower than, equal to, and
**faster than** `clk_sys`, including a non-integer ratio.

- Reference-model comparison (Python `deque`) over at least 100 000 samples at every
  clock ratio: every sample and every coordinate matches, in order.
- **Overflow counting is exact.** Stall `rd_tready` for a known number of cycles
  while the write side streams, and assert `overflow_count` equals the exact number
  of samples lost. Not "greater than zero" — exact. An overflow counter off by the
  burst length is worse than none, because it will be trusted.
- `overflow_sticky` latches and survives until reset, including across a long quiet
  period after the burst.
- `high_water` equals the true peak occupancy across a run with randomized
  backpressure.
- Write-side reset while the read side is draining: read side completes cleanly, no
  spurious samples, telemetry preserved where it is supposed to be.
- `clk_px` stops entirely mid-stream: read side drains what is in the FIFO and then
  goes idle; nothing deadlocks.
- A test asserting that the module's documented depth arithmetic (requirement 2)
  holds for the configured worst-case stall — i.e. inject exactly that stall and
  assert **zero** overflow.
- `check_stream_protocol` on both interfaces.

## References

- `rtl/RTL_PLAN.md` §3
- `I-01` (`fifo_async`)
- `D-05` (CSR counters and high-water marks)
