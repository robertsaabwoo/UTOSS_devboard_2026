---
id: V-02
title: "VERIFICATION: camera model BFM — real timing, synthetic frames, and malformed frames"
labels: [verification, P0, "area:datapath", "size:M", good-first-issue]
depends_on: []
---

## What

A cocotb camera model that drives the FPGA's video input at realistic timing, and
that can be told to misbehave in every way a real camera misbehaves.

## Why it is P0 and unblocked

`rtl/RTL_PLAN.md` "Verification" item 2. `DP-01`, `DP-04` and `DP-05` all need it,
and every one of their acceptance criteria is phrased in terms of the model doing
something wrong on purpose. Without it those benches can only test the happy path,
which is the path that never causes a problem.

It also depends on nothing. It can be written today, in parallel with `V-01`, before
any camera decision is made — the interface specifics are parameters.

## Deliverables

- `rtl_tests/common/utoss_tb/camera_model.py`
- Its own unit tests (a loopback bench that drives the model into a trivial capture
  module and checks the model itself behaves as configured)
- `docs/CAMERA_MODEL.md` — every fault it can inject, and which bench uses which

## Interface

```python
class CameraModel:
    def __init__(self, dut, *,
                 width=640, height=480, bands=1, bit_depth=12, bus_width=14,
                 pclk_mhz=75.0,
                 hsync_active=1, vsync_active=1, sample_rising=True,
                 h_blank=16, v_blank=8,       # realistic blanking, not zero
                 packing=False,
                 seed=None): ...

    def pattern(self, kind="gradient"): ...   # gradient|noise|constant|counter|cube
    async def send_frames(self, n=1): ...
    async def send_cube(self, cube): ...      # a numpy array, so V-01 can share it
    def stop_clock(self): ...                 # the camera stops streaming entirely

    # Fault injection -- the point of the module
    def inject(self, fault, *, at_frame=None, at_line=None, count=1): ...
```

## Faults it must be able to inject

Each one maps to an acceptance criterion in `DP-01`, `DP-04` or `DP-05`:

| Fault | Exercises |
|---|---|
| `short_line` — a line with fewer pixels | `DP-01` resync, `DP-04` geometry error |
| `long_line` — a line with more pixels | `DP-01` resync |
| `short_frame` — a frame with fewer lines | `DP-01`, `DP-04` |
| `long_frame` | `DP-04` discard-and-count |
| `missing_vsync` | `DP-01` frame alignment |
| `missing_hsync` | `DP-01` line alignment |
| `sync_glitch` — a one-cycle pulse on HSYNC/VSYNC | `DP-01` glitch rejection |
| `clock_stop` / `clock_restart` | `DP-01` `no_pclk`, `I-02` |
| `clock_jitter` — period varying within spec | `DP-05` CDC across a non-ideal clock |
| `garbage_in_blanking` — data toggling outside valid | `DP-01` enable gating |
| `partial_frame_at_enable` — streaming already mid-frame when `enable` rises | `DP-01` frame-boundary start |
| `bit_stuck` — one data line stuck high or low | `DP-04` pattern tests |

## Requirements

1. **Realistic blanking by default.** `h_blank` and `v_blank` default to non-zero. A
   model with zero blanking produces a gapless pixel stream that no real sensor
   produces, and a receiver tested only against it will fail on hardware — this is the
   most common way a camera model flatters the DUT.
2. **The clock is the model's.** It drives `clk_px`, and it must be able to stop,
   restart, and jitter. The DUT does not get to assume a clock is always there; the
   camera is power-gated.
3. **Every parameter in `DP-01`'s port list is a model parameter** — polarity,
   sampling edge, bus width, bit depth, packing. The `DP-01` bench sweeps them, so the
   model must too.
4. **Shared cube format with `V-01`.** `send_cube` takes the same numpy array
   `tools/gen_cube.py` produces, so the same cube goes through the software model and
   the hardware, which is what makes `V-03` possible. Coordinate with `V-01` on this
   rather than inventing a second format.
5. **The model records what it actually sent**, pixel by pixel, including under fault
   injection. The bench compares the DUT's output against *that*, not against what was
   requested. Under `short_line` those differ, and the whole point is checking the DUT
   handled what really arrived.
6. **Faults are deterministic and seeded.** A failure that cannot be reproduced is a
   failure nobody will fix.

## Acceptance criteria

- Drives a nominal frame at the configured timing; a loopback test confirms the
  pixel sequence, blanking intervals and sync polarity are exactly as configured.
- Every fault in the table above is implemented, has a unit test proving the model
  really produces the malformation, and is referenced by at least one `DP-*` bench.
- `send_cube` round-trips a numpy cube: every sample arrives, in the documented
  `(x, y, band)` order.
- Clock stop and restart mid-frame works, and the model's own recorded output reflects
  it.
- Same seed produces a byte-identical stimulus run twice.
- `docs/CAMERA_MODEL.md` lists every fault and which bench consumes it.

## Notes

Good first issue for someone who would rather write Python than Verilog, and it
unblocks three RTL issues. Write it alongside `DP-01` rather than after — the two
benches should be developed together, with the model's faults driven by what `DP-01`
needs to prove.

## References

- `rtl/RTL_PLAN.md` "Verification" (item 2)
- `DP-01`, `DP-04`, `DP-05` acceptance criteria
- `io_specs/camera.yaml`, `io_specs/fpga.yaml` (`DCMI_RX`)
