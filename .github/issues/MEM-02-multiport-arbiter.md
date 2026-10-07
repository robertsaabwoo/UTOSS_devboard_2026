---
id: MEM-02
title: "RTL: multi-port DDR3 arbiter (camera write, compressor read + working set, storage read)"
labels: [rtl, P0, "area:memory", "size:L"]
depends_on: [MEM-01, D-03, I-01]
---

## What

The arbiter that shares the single DDR3 port between the four clients that want
it. One of the two pieces we write around the controller
(`rtl/RTL_PLAN.md` §5).

## The ports, and why their priorities are not equal

| Port | Direction | Deadline |
|---|---|---|
| Camera write | write | **Hard.** The camera cannot be stalled. Miss it and pixels are lost permanently. |
| Compressor read (neighbourhood fetch) | read | Soft — stalling it slows compression, which only matters if the capture outruns it. |
| Compressor working set (weights/state) | read/write | Soft, but latency-sensitive: it is in the predictor's inner loop. |
| Storage read (offload) | read | Soft. Runs after the capture if `D-04` chose buffer-then-offload. |
| Calibration read (`DP-06`) | read | Soft, but one read per sample — a large bandwidth claim. |

**The camera write port must never be starved.** It is the only client whose data
cannot be regenerated. Everything else can wait; a lost pixel is lost for the
orbit. A round-robin arbiter that treats all five equally will drop pixels under
load, and the symptom will be an `overflow_count` in `DP-05` that nobody can
explain.

## Interface

```verilog
module ddr_arbiter #(
    parameter integer N_PORTS = 5,
    parameter integer ADDR_W  = 28,
    parameter integer DATA_W  = 128,
    parameter integer ID_W    = 4,
    // Port 0 is the camera write port and is privileged -- see requirement 1.
    // Burst length per grant: longer is more efficient against DDR row
    // activates and worse for the latency of every other port. The right value
    // comes from the D-03 analysis, not from taste.
    parameter integer MAX_BURST = 8
) (
    input  wire                        clk_sys,
    input  wire                        rst_sys_n,

    // Per-port request interfaces (flattened; one group per port)
    input  wire [N_PORTS-1:0]          req_valid,
    output wire [N_PORTS-1:0]          req_ready,
    input  wire [N_PORTS-1:0]          req_write,
    input  wire [N_PORTS*ADDR_W-1:0]   req_addr,
    input  wire [N_PORTS*DATA_W-1:0]   req_wdata,
    input  wire [N_PORTS*DATA_W/8-1:0] req_wmask,

    output wire [N_PORTS-1:0]          rsp_valid,
    input  wire [N_PORTS-1:0]          rsp_ready,
    output wire [N_PORTS*DATA_W-1:0]   rsp_rdata,

    // To the DDR wrapper (MEM-01)
    output wire                        ddr_cmd_valid,
    input  wire                        ddr_cmd_ready,
    output wire                        ddr_cmd_write,
    output wire [ADDR_W-1:0]           ddr_cmd_addr,
    output wire [ID_W-1:0]             ddr_cmd_id,
    output wire [DATA_W-1:0]           ddr_wr_data,
    output wire [DATA_W/8-1:0]         ddr_wr_mask,
    input  wire                        ddr_rd_valid,
    output wire                        ddr_rd_ready,
    input  wire [DATA_W-1:0]           ddr_rd_data,
    input  wire [ID_W-1:0]             ddr_rd_id,

    // Telemetry, per port, all saturating
    output wire [N_PORTS*32-1:0]       grant_count,
    output wire [N_PORTS*16-1:0]       max_wait_cycles,   // worst-case latency seen
    output wire [15:0]                 err_camera_starved // see requirement 2
);
```

## Behaviour requirements

1. **Port 0 (camera write) has absolute priority**, bounded only by the burst
   already in flight. Document the resulting worst-case latency for every other
   port — `DP-05`'s depth and `CMP-01`'s stall tolerance both depend on it.
2. **Starvation of the camera port is a reportable error.** If port 0 waits longer
   than a configured threshold, increment `err_camera_starved`. That threshold is
   derived from `DP-05`'s FIFO depth: if the camera port waits longer than the FIFO
   can absorb, pixels **will** be lost, and the arbiter knew first. Reporting it here
   makes the cause diagnosable instead of leaving an unexplained overflow count.
3. **No other port may be starved indefinitely either.** Below port 0, use a fair
   scheme with an explicit aging or weighting rule, and write the rule down. A
   compressor that never gets its weights is a payload that never finishes a cube.
4. **`max_wait_cycles` per port** is the measurement that makes the whole budget
   real rather than theoretical. It goes to the CSR and it is the number to look at
   first when a capture misbehaves.
5. **Bursts, not single beats.** The whole point of `D-03`'s layout work is DDR row
   efficiency; an arbiter that interleaves single transfers from five ports will
   thrash rows and throw that away. `MAX_BURST` is a real parameter with a real
   trade-off: measure both bandwidth and worst-case latency across its range and
   publish the curve.
6. **Response routing by `cmd_id`.** If `MEM-01` can return reads out of order, the
   arbiter must route each response to the right port. Tag with the port index plus a
   sequence number. If the configuration guarantees in-order responses, say so in the
   header and depend on `MEM-01`'s documented guarantee explicitly.
7. Per-port request FIFOs come from `I-01`, including their `overflow` and
   `high_water` outputs, which go to the CSR.
8. Unused ports (`DP-06` disabled, storage idle) must cost nothing in latency for
   the others — a port with no request pending must not consume a grant slot.

## Resource budget

Expect 800–1500 LUTs and 1000+ FFs, dominated by the per-port FIFOs and the wide
data muxing at `DATA_W=128`. The FIFOs should land in EBR; check with
`tools/dev synth`. Set `synth.budget` from a measured run — this is one of the
blocks most likely to surprise.

## Acceptance criteria

- **Reference model**: a Python arbiter implementing the documented priority and
  aging rule. Compare grant order beat for beat over randomized traffic. A bench
  that only checks "data eventually arrives" will not catch a priority inversion.
- Every port's read returns its own data, never another port's. Drive each port
  with a distinct pattern and assert on it — this is the failure that silently
  mixes a calibration frame into a cube.
- **Camera priority**: all five ports requesting continuously — port 0's
  worst-case wait is within the documented bound, and the bench asserts the exact
  bound rather than a vague inequality.
- **Starvation detection**: force port 0 to wait past the threshold (hold the DDR
  port busy) and assert `err_camera_starved` increments.
- **No starvation below port 0**: with port 0 at 100 % duty, every other port still
  makes progress, and the bench asserts a bound on their wait too.
- Out-of-order responses from the `MEM-01` model are routed correctly.
- **Bandwidth and latency measured** across `MAX_BURST` values of 1, 4, 8 and 16,
  with the `D-03` access pattern, published in the pull request. The chosen default
  must be justified by that data.
- Per-port request FIFO overflow is counted, not silent.
- Reset mid-burst leaves the DDR port in a sane state and no port deadlocked.
- `check_stream_protocol` on every port interface.

## References

- `rtl/RTL_PLAN.md` §5
- `D-03` (access pattern and burst efficiency), `MEM-01` (measured bandwidth,
  refresh stall, response ordering), `DP-05` (FIFO depth that sets the starvation
  threshold)
