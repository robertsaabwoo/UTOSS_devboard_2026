---
id: D-04
title: "DECISION: SD interface — SPI mode vs 4-bit SDIO, and the offload timing budget"
labels: [decision, P1, hardware, "area:storage", "size:S"]
depends_on: []
---

## What has to be decided

Whether the SD card is driven in **SPI mode** (~1–5 MB/s, small RTL) or **4-bit
SDIO** (~20–25 MB/s, substantially more RTL: command/response FSM, CRC7 and
CRC16, card-initialisation sequence, tight data timing).

This is a real architectural lever, not a preference, and the answer follows from
one timing question.

## The timing argument to settle

From `rtl/RTL_PLAN.md` §8: live 20 MB/s is only required if we write to the card
**during** capture. If instead the pass is buffered in DDR3 and offloaded
afterwards, then 2.4 GB at 5 MB/s is about 8 minutes — comfortable against a
1–2 min/day duty cycle. That likely removes the need for SDIO entirely, and with
it the hardest part of the storage block.

So the decision needs:

- [ ] The real worst-case capture size, in bytes, after compression — which
      depends on the CCSDS 123 compression ratio actually achieved on
      representative data (see `V-01`), not on an assumed ratio.
- [ ] Confirmation that it fits in the fitted DDR3. "A couple of gigabytes" of
      DDR3 against ~1.2–2.4 GB of raw pass data is tight **before** compression
      and comfortable after it — so the answer depends on whether we buffer raw
      or compressed, which is itself part of this decision.
- [ ] The power cost of the offload window: the FPGA and the card are powered for
      those 8 minutes. Against a 75 W satellite budget and a 0.3 W payload target
      this is probably fine, but it is energy that has to be in the budget rather
      than discovered in it. Cross-check against `scripts/check_power_rules.py`.
- [ ] The failure mode if a pass is interrupted mid-offload. Buffering in
      volatile DDR means a power loss between capture and offload loses the
      capture outright.

## What to produce

- [ ] The decision, with the timing and energy arithmetic, in
      `docs/STORAGE_PLAN.md`.
- [ ] Card selection: industrial-grade SD, with its write-endurance and
      power-loss behaviour noted. A consumer card that does internal wear
      levelling at an unpredictable moment can stall a write for hundreds of
      milliseconds, which matters a great deal if the decision is "write live"
      and not at all if it is "offload afterwards".
- [ ] `io_specs/` entries for the SD signals at the chosen width, with the pin
      count that implies.
- [ ] Either unblock `ST-01` (SPI) as the only storage work, or keep `ST-02`
      (SDIO) open with the live-write requirement stated.

## Acceptance criteria

- One mode chosen, with the sustained rate it must achieve and where that number
  comes from.
- Pin count and `io_specs` updated, so the pinout work in `D-02` can account for
  it.
- The buffer-then-offload power cost is in the power budget.

## References

- `rtl/RTL_PLAN.md` §8
- `UTAT Meeting.txt`: 75 W max for the whole satellite, 0.3 W is fine for us
- `io_specs/power.yaml`, `scripts/check_power_rules.py`
