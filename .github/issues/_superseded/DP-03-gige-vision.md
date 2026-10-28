---
id: DP-03
title: "RTL: GigE Vision receiver — RGMII/MAC, UDP/IP, GVSP depacketizer, GVCP control (BLOCKED on D-01)"
labels: [rtl, blocked, P1, "area:datapath", "size:XL", hardware]
depends_on: [D-01, I-01, I-02]
blocked_by_decision: D-01
---

## Blocked — but one of the two likely outcomes

**Do not start the RTL.** It only applies if `D-01` chooses GigE Vision, and if
`D-01` chooses Camera Link or parallel this issue closes.

But note that this is **not** a remote contingency: at the 2026-09-05 meeting
the client stated the interface as Camera Link or GigE, so this and `DP-02` are
the two probable answers.

That matters more here than anywhere else in the breakdown, because this option
**changes the PCB** — a PHY, magnetics and a connector that
`hardware/devboard.kicad_sch` does not have, with their own rails, `io_specs`
entries and ERC consequences. The schematic work has a January deadline. If
there is any chance the answer is GigE, the board-level checklist below has to
be worked through *before* layout, not after `D-01` formally closes.

## What it would involve

- RGMII interface to an external PHY (and therefore: a PHY, magnetics, and an RJ45
  or M12 connector on the board — none of which are in `hardware/devboard.kicad_sch`
  today)
- An Ethernet MAC. **Use an existing core**; writing a MAC is not the value we add.
- UDP/IP, enough of it to receive a stream and answer control requests
- **GVSP** stream depacketizer — this is the part we would write
- **GVCP** control channel for camera configuration and discovery

## The part that is usually underestimated

GVSP streams over **UDP**, so packet loss and reordering are ours to handle. On a
point-to-point link with one camera the loss rate should be very low, but "should
be" is not an architecture:

- a reordering window, and therefore a reassembly buffer, sized for the worst case
- a resend request path (GVSP supports packet resend) or an explicit decision that
  a lost packet means a dropped line, recorded in telemetry
- per-block and per-packet ID tracking, so a lost packet is **detected** rather
  than quietly producing a cube with a line of stale data in the middle

That last point is the real risk. A silently dropped packet produces an image that
looks plausible and is wrong, in a capture that cannot be re-taken.

## If this is chosen, before any RTL is written

- [ ] Confirm the camera's GigE Vision version and which GVSP/GVCP features are
      mandatory for it.
- [ ] Pick the MAC core and confirm its licence is compatible with publishing this
      repository (it is an open-source devboard).
- [ ] Add the PHY, magnetics and connector to the schematic, with their own power
      and `io_specs` entries. This is a PCB change with its own ERC and power
      implications — not an RTL-only decision.
- [ ] Budget the reassembly buffer in DDR3 or EBR and check it against
      `rtl/ecp5_target.yaml`.
- [ ] Decide the loss policy: resend, or drop-and-report. Write it down.
- [ ] Confirm the RGMII timing is achievable at the ECP5's I/O rates in TQFP-144
      with the required `VCCIO`.

## Rough scope if it goes ahead

MAC (existing core) 1500–2500 LUTs, UDP/IP 800, GVSP depacketizer 1000+, GVCP 600,
plus the reassembly buffer. Call it 4000+ LUTs — the single largest block in the
design, larger than the compressor.

## Acceptance criteria (if it proceeds)

To be specified once `D-01` resolves. At minimum: a packet-level model that injects
loss, duplication and reordering; a test that **every** lost packet is reported in
telemetry and never silently filled; and a sustained-rate test at the camera's real
data rate with the reassembly buffer at its configured size.

## References

- `rtl/RTL_PLAN.md` §1 (GigE Vision)
- `hardware/devboard.kicad_sch` — no PHY or magnetics present today
- `UTAT Meeting.txt`: "Interfacing with the downstream can be done over CAN" —
  note that is the *downstream* bus, not the camera link
