---
id: H-01
title: "HARDWARE: devboard.kicad_sch has no electrical connectivity — 13 ERC errors, red since August"
labels: [hardware, P0, "size:M"]
depends_on: [D-01, D-02]
---

## What is wrong

`hardware/devboard.kicad_sch` fails ERC with **13 errors and 23 warnings**, and has
done on every CI run since `6e3ef16` ("CI: make ERC an actual gate") in August. The
gate is not broken — it is correctly reporting that the schematic has no working
connectivity.

Reproduce it locally:

```bash
docker run --rm -v "$PWD:/work" -w /work kicad/kicad:9.0 \
  kicad-cli sch erc --format json --severity-all \
    hardware/devboard.kicad_sch --output erc.json
```

## The violations

```
6 x pin_not_connected      #PWR02 VIN_12V, #PWR03 +5V, #PWR04 +3V3,
                           #PWR01 GND, U1 pin 2 GND, U2 pin 2 GND
6 x power_pin_not_driven   the same six pins
1 x label_dangling         Label 'GND'

23 warnings: 11 x endpoint_off_grid, 12 x lib_symbol_issues
```

## Two root causes

**1. Nothing is actually connected.** Eleven pins sit off-grid — `J1`, `C1`, `C2`,
`C3`, `U1.VIN`, `U2.VIN`, `J2`, `J3` and three power flags. The sheet was authored
as text rather than drawn in KiCad, so wire endpoints do not land on pin positions.
The six `pin_not_connected` errors are the direct consequence: KiCad sees pins with
nothing attached, because electrically there *is* nothing attached.

This is the one that matters. A netlist generated from this sheet would not describe
the circuit somebody intended to draw, so no downstream check of it means anything.

**2. No `PWR_FLAG` symbols on externally-supplied rails.** `VIN_12V` arrives from a
barrel jack and `GND` from the connector shell, so no output-power pin drives either.
Without a `PWR_FLAG` asserting "this rail is supplied from off-sheet", ERC reports all
six power-input pins as undriven. This half is a two-minute fix once (1) is resolved.

## The larger problem: the sheet is the wrong board

Beyond ERC, this schematic is a 288-line, 12-symbol placeholder: barrel jack ->
5 V LDO -> 3V3 LDO, three capacitors, three pin headers. It predates the ECP5
retarget in `fd3e621`.

The `io_specs/` now describe a completely different board — a bare ECP5 on gated
rails, a camera sensor, an always-on supervisor CPU configuring the FPGA over slave
mode, JTAG, DDR3, SD. **None of that is on the sheet.** So the cross-module logic
checks in `scripts/check_logic_spec.py` are validating a spec graph against a
schematic that does not contain the parts the graph is about.

Fixing ERC on the current sheet would therefore be fixing the wrong artifact. The
real work is drawing the board the io_specs describe.

## Why it is P0

- **The PCB layout has a January deadline** (`UTAT Meeting.txt`: "In January, we
  should have our Verilog and PCB layout done"). The RTL side now has its harness and
  a 33-issue breakdown; the schematic side has a placeholder.
- A permanently-red required check trains everyone to ignore CI. That is a worse
  outcome than having no check, because it also hides the next real failure.
- It interacts with the merge blocker below.

## Related: `main` is unmergeable for an unrelated reason

The `Baseline` ruleset on `main` requires two status checks named `Schematic ERC`
and `Power rail SPICE verification`. Commit `3b9b4f6` ("CI: split into per-module
jobs") renamed those jobs to `power / Schematic ERC` and
`power / SPICE sweep verification`. The required contexts no longer exist, so they
can never report, and **every** PR into `main` shows `BLOCKED` regardless of whether
CI passes.

Note the ordering trap: correcting those names makes the ERC requirement *real*, at
which point the 13 errors above genuinely block every merge. So either this issue is
fixed first, or `Schematic ERC` is temporarily dropped from the required list with a
note pointing back here. Decide deliberately rather than discovering it on the next
PR.

## Work to do

- [ ] Decide whether to repair the existing sheet or redraw the board from
      `io_specs/` (almost certainly redraw — see above). It depends on `D-01` for the
      camera interface and `D-02` for the confirmed part and package.
- [ ] Draw it in KiCad, on-grid, so pins and wires actually connect.
- [ ] Add `PWR_FLAG` on every externally-supplied rail.
- [ ] Clear the 12 `lib_symbol_issues` warnings: the sheet references symbols whose
      cached definition does not match the library. Vendor the real symbols into
      `libraries/symbols/`.
- [ ] Fix the `Baseline` ruleset contexts, in whichever order the trap above makes
      sensible.

## Acceptance criteria

- `kicad-cli sch erc --severity-error --exit-code-violations` exits 0.
- `endpoint_off_grid` warnings are zero. Off-grid endpoints mean a connection that
  looks right on screen and is not real; leaving them as warnings is how the current
  state happened.
- `lib_symbol_issues` warnings are zero.
- `scripts/check_logic_spec.py` passes for all five modules against a schematic that
  actually contains the ECP5, the camera connector and the supervisor.
- Every net in `io_specs/*.yaml` exists on the sheet, and every net on the sheet is in
  the io_specs. A mismatch in either direction is a spec or a schematic bug.
- `main`'s required checks name jobs that exist, and a PR into `main` can reach a
  mergeable state.

## References

- `hardware/devboard.kicad_sch`, `hardware/FLOORPLAN.md`
- `io_specs/fpga.yaml`, `io_specs/camera.yaml`, `io_specs/supervisor.yaml`,
  `io_specs/power.yaml`
- `6e3ef16` (made ERC a gate), `3b9b4f6` (renamed the jobs), `fd3e621` (ECP5 retarget)
- `UTAT Meeting.txt`: January deadline for Verilog and PCB layout
