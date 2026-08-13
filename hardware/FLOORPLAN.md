# Devboard Hardware Project Structure — Example (Power / FPGA / UART I/O)

This is a simplified example project (superseding the earlier `/initial_roles`
mapping for now) to establish the workflow with three submodules:

1. **power** — 12V in, regulates to 5V (FPGA core board) and 3.3V (carrier peripherals)
2. **fpga** — carrier-side interface to the purchased QMTECH XC7A-series
   Artix-7 core board (vendor manuals: see `owner_doc` in `io_specs/fpga.yaml`,
   not vendored into this repo). This carrier does **not** place the raw BGA
   chip — the FPGA itself lives on the purchased module.
3. **uart_io** — USB-to-UART bridge IC for the FPGA Linux console (no MCU)

Each submodule has a spec at `io_specs/<name>.yaml` transcribing its
constraints in machine-readable form for CI, per the tooling discussed
earlier (kicad-cli ERC/DRC + spec checks).

## Repo layout

```
hardware/
  devboard.kicad_pro
  devboard.kicad_sch          # ROOT sheet: instantiates the 3 sheets below
  sheets/
    power.kicad_sch
    fpga.kicad_sch
    uart_io.kicad_sch
  devboard.kicad_pcb

io_specs/
  power.yaml
  fpga.yaml
  uart_io.yaml

spice/
  power/                      # only submodule with real analog verification value
```

`fpga` and `uart_io` are digital/interface modules — connector pin mapping
and logic-level checks (ERC + `io_specs` cross-check) cover them; there's no
`spice/fpga/` or `spice/uart_io/` because there's no analog behavior to
verify with a transient simulation. `power` is where SPICE earns its keep
(regulator load transient, ripple under the 2A/5V load).

## Constraints summary

| Net | Rail | Min | Max | Current | Notes |
|---|---|---|---|---|---|
| VIN_12V | power | 11.4V | 12.6V | — | barrel jack, reverse-polarity + PTC fuse |
| +5V | power → fpga | 4.9V | 5.1V | 2.0A min | ripple <30mV, feeds core board |
| +3V3 | power → uart_io | 3.2V | 3.4V | 0.5A min | carrier-local, don't tap core board's 3.3V |
| GPIO_BANK | fpga ↔ uart_io | 3.135V | 3.465V | — | LVCMOS33, fixed by core board, no 5V tolerance |

Full detail in `io_specs/*.yaml`.

## Open item — you're likely missing a module

**JTAG / programming path is unresolved.** Whether the carrier needs its own
JTAG header depends on whether the QMTECH core board has onboard USB-JTAG or
only exposes raw TCK/TMS/TDI/TDO pins. This wasn't confirmed (PDF manuals
weren't vendored into this repo — see `owner_doc` in `io_specs/fpga.yaml` for
the vendor source) — logged as an open item there. If the core board doesn't
have onboard USB-JTAG, you need either:
- a 4th submodule (`jtag`) with a standard 2x7 0.05" Xilinx-style header, or
- fold a JTAG header into the `fpga` sheet since it's directly tied to the
  core-board interface.

Without this, the board has no way to load a bitstream. Confirm from the
vendor manuals before finalizing the `fpga` sheet.

Secondary (lower priority, likely already covered by the core board itself,
worth a quick confirm): clock source (core board typically has its own
oscillator) and config-mode strapping (PROG_B/DONE/INIT_B, if exposed —
nice to wire a reset button to PROG_B but not blocking).

## Next step

Create `devboard.kicad_pro`/`devboard.kicad_sch` via the KiCad GUI, add the
three sheets above, and resolve the JTAG open item before routing the `fpga`
sheet.
