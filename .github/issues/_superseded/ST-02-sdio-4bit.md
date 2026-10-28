---
id: ST-02
title: "RTL: 4-bit SDIO upgrade for live writing during capture (only if D-04 requires it)"
labels: [rtl, blocked, P2, "area:storage", "size:L"]
depends_on: [D-04, ST-01]
blocked_by_decision: D-04
---

## Blocked

**Do not start this until `D-04` says it is needed.** If `D-04` concludes that
buffering the pass in DDR and offloading afterwards is sufficient — which
`rtl/RTL_PLAN.md` §8 expects — close this issue. SPI mode in `ST-01` is then the
whole storage story.

## When it would be needed

Only if the payload must write to the card **during** capture at the full ~20 MB/s.
SPI mode tops out around 1–5 MB/s, so live writing forces 4-bit SDIO at ~20–25 MB/s.

Two things could force it:

- The compressed stream does not fit in DDR, so it cannot be buffered. That is a
  `D-04` finding, and it depends on the compression ratio measured in `V-01`.
- A requirement that a capture survives a power loss immediately after it is taken,
  which buffering in volatile memory cannot provide.

Both are real possibilities. Neither should be assumed.

## What it would add on top of `ST-01`

- 4-bit data bus with its own CRC16 per line, not one across the bus
- A full command/response FSM over the SD command line (SPI mode's simpler framing
  does not apply)
- The complete card-identification sequence in SD mode: CMD0, CMD8, ACMD41, CMD2,
  CMD3, CMD7, ACMD6 to switch to 4-bit
- Much tighter data timing — this is the part that makes it hard. At 25 MHz on a
  4-bit bus the setup and hold windows are real constraints that need proper
  `.lpf` timing in `I-03` and may need an `IDDRX`-based capture
- Real-time write streaming with no gaps, which means the write path can never stall
  on an arbiter grant — a new constraint on `MEM-02`

`rtl/RTL_PLAN.md` budgets ~2k LUTs for SDIO. The timing work is the larger cost.

## If it proceeds, the critical extra tests

Beyond everything in `ST-01`:

- Per-line CRC16 on all four data lines, each verified independently against
  published vectors. Three lines correct and one wrong is the failure that passes a
  naive test.
- **Sustained write at full rate with no gaps**, for the full duration of a capture —
  not a short burst. The point of SDIO is sustained rate; a test that writes 100 blocks
  proves nothing about minute 2.
- **Card going busy mid-stream** at the worst possible moment, with the measured
  `max_busy_cycles` from `ST-01` as the input. If the card can go busy for 200 ms, the
  write path needs 200 ms of buffering at 20 MB/s — 4 MB — and that has to come from
  somewhere. Work this out before writing RTL; it may make live writing impossible
  regardless of interface speed, which would settle `D-04` by itself.
- Timing closure at the full clock rate in `I-03`, on the real package.

## References

- `rtl/RTL_PLAN.md` §8
- `D-04`, `ST-01` (`max_busy_cycles` measurement), `MEM-02` (no-stall constraint)
