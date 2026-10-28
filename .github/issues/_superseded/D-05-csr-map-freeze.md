---
id: D-05
title: "DECISION: freeze the supervisor CSR register map as a machine-readable contract"
labels: [decision, P0, "area:control", "size:S"]
depends_on: []
---

## What has to be decided

The register map the supervisor CPU sees, frozen as a file that both the RTL and
the supervisor firmware generate from — not two hand-maintained copies.

## Why this comes before the RTL

The client asked for exactly this: *"They expect us to provide them the tools to
talk to the CPU."* The register map **is** that interface. Two things follow:

- It is the contract between two teams working in parallel (the meeting notes ask
  for Verilog and software written in parallel). A contract that lives in two
  hand-written copies — one in Verilog `localparam`s, one in a C header — will
  disagree, and the symptom will be a payload that reports the wrong status
  rather than an obvious error.
- `C-01` cannot be built without it, and `C-05`, `DP-05`, `MEM-02` and `CMP-01`
  all need to know which counters and status bits they are expected to expose.

## What to produce

- [ ] `rtl/fpga/csr_map.yaml` — the single source of truth. One entry per
      register: address, width, access (`ro` / `rw` / `w1c` / `rw1s`), reset
      value, bit fields, and a one-line description of what the field means to
      the operator. Not to the designer — to the operator.
- [ ] `scripts/gen_csr.py` generating, from that file:
      - `rtl/fpga/csr_defs.vh` — address and field constants for the RTL
      - `firmware/csr_defs.h` — the same for the supervisor
      - `docs/CSR_MAP.md` — the human-readable table for the client
- [ ] A CI check that the generated files are in sync with the YAML, so a hand
      edit to a generated file fails the build instead of silently diverging.

## Registers the map must contain

From `rtl/RTL_PLAN.md` §10, plus what the other blocks need to expose. Addresses
and exact field layout are yours to choose; the content is not.

| Group | Must include |
|---|---|
| Identity | magic/ID word, RTL version (from git describe, baked into the bitstream), build date |
| Control | capture start, capture stop, soft reset, mode select |
| Camera | exposure, gain, mode — plus pass-through to the camera's own UART command path (`C-03`) |
| Compression | CCSDS 123 parameters: prediction bands *P*, weight resolution, encoder options, lossless/near-lossless selection |
| Status | state of the capture FSM, PLL lock per domain, DDR3 calibration done, ready flag |
| Counters | frames captured, lines captured, bytes written, compressed bytes out |
| Errors | every FIFO overflow count, framing errors, short/malformed frames, DDR3 error flags, SD write errors, CRC failures |
| High-water marks | peak occupancy of every FIFO on the path |
| Health | heartbeat/liveness for the supervisor's watchdog, configuration CRC status (`C-05`) |

Rules the map has to follow:

- **Every error counter saturates; it must not wrap.** A wrapped counter can read
  zero after a storm of errors, which is indistinguishable from a clean pass. The
  capture cannot be re-taken, so "we do not know whether this cube is good" is a
  real cost.
- Counters and high-water marks are **`w1c` or explicitly cleared on capture
  start**, and which one it is must be stated. Ambiguity here means the ground
  team cannot tell whether a count belongs to this pass or to the last one.
- Reserved fields read zero and ignore writes, so the map can grow without
  breaking older firmware.
- A multi-word quantity (a 64-bit byte count) needs a defined atomic read: latch
  the whole value when the low word is read, or provide a snapshot bit. Reading
  two halves that moved between accesses yields a number that was never true.

## Acceptance criteria

- `rtl/fpga/csr_map.yaml` exists and `scripts/gen_csr.py` regenerates all three
  outputs deterministically.
- CI fails if a generated file is edited by hand.
- `docs/CSR_MAP.md` is good enough to hand to the bus team as the payload's
  interface document.
- `C-01` can be implemented against it with no further questions.

## References

- `rtl/RTL_PLAN.md` §10
- `io_specs/supervisor.yaml` (`open_items/supervisor-config-mode`)
- `UTAT Meeting.txt`: "They expect us to provide them the tools to talk to the
  CPU"; "need to get reset controls of the camera and all other controls of the
  camera that the ground station can have control of"
