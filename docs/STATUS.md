# Current numbers

Every figure here was produced by running the repo's own checks on
`feature/rtl-verification-harness`, not transcribed from a plan. Regenerate it
with the commands shown.

**Measured 2026-10-07.**

---

## Power

```bash
python3 scripts/check_power_rules.py     # budget, ramp rates, bring-up sequence
python3 scripts/run_power_sweep.py       # ngspice operating-point sweeps
```

### Budget — PASSED

| State | Draw | Allowed | Margin |
|---|---:|---:|---:|
| `payload_active` | **2028.1 mW** | 2500 mW | 81 % used |
| `payload_idle` | **214.4 mW** | 350 mW | 61 % used |

`payload_idle` is the number that matters for orbit-average energy: the payload
images for one to two minutes a day and is in this state for the rest of the
orbit, with `+1V1`, `+2V5`, `+3V3_FPGA` and `CAM_5V` all gated off.

It also reconciles the apparent conflict with the client's *"0.3 W is fine"*.
Idle is **0.214 W**, inside that. Active is 2.0 W, but for ~2 min/day, which is
about 2.8 mWh per orbit-day — negligible against a 75 W satellite. Power gating
is the entire reason an ECP5 is viable here; without it the ~125 mW static floor
would be paid continuously.

### Active-state breakdown

| Rail | Consumer | Static | Dynamic allowance | Source |
|---|---|---:|---:|---|
| `+1V1` | `fpga.VCC` | 77 mA | 173 mA | ECP5 Table 3.8 ICC typ |
| `+2V5` | `fpga.VCCAUX` | 16 mA | 9 mA | ECP5 Table 3.8 ICCAUX typ |
| `+3V3_FPGA` | `fpga.VCCIO` | 4 mA | 46 mA | Table 3.8, 0.5 mA/bank × 7 |
| `+3V3_SYS` | `supervisor.VDD` | 30 mA | 20 mA | **PLACEHOLDER** — no part selected |
| `CAM_5V` | `camera.VDD` | 0 mA | 200 mA | **PLACEHOLDER** — no part selected |

Two of the five rails are placeholders, so 2028 mW is not a final number in
either direction.

### ⚠ The budget is still built on 25F figures

`io_specs/power.yaml` sources its static currents as *"ECP5 Table 3.8 ICC typ,
**LFE5U-25F**"*. The RTL now targets the **45F** (`rtl/ecp5_target.yaml`), which
is a larger die and therefore draws more static current on `+1V1` and `+2V5`.

At 81 % of the active allowance already, this is not slack to absorb a part
change silently. The 45F's ICC and ICCAUX have to be transcribed from
FPGA-DS-02012 and the budget re-run before anyone treats 2028 mW as the number.
Tracked in **#14 (D-02)**.

### Ramp and bring-up sequencing — PASSED

| Rule | Margin | Required |
|---|---:|---:|
| `vccio8-before-core` | **4.176 ms** | 1.0 ms |
| `vccio8-before-vccaux` | **4.118 ms** | 1.0 ms |

VCCIO8 must reach its POR trip point (1.06 V worst case) before VCC reaches
1.00 V and VCCAUX reaches 2.20 V, so the supervisor never observes a floating
`PROGRAMN`/`INITN`/`DONE` during bring-up. Comfortable margins on both.

Ramp rate held inside 0.01–10 V/ms on all rails, with the `+2V5` ceiling of
30 V/ms (Table 3.2 note 4) enforced separately.

### SPICE — PASSED

`line_and_load` sweep, **16 operating points** across `vin` × `rload_core`.
Every rail regulates inside its specified window at every point.

---

## RTL

```bash
tools/dev all        # or: tools\dev.cmd all
```

### Verification — PASSED

| Bench | Parameter sets | Tests | Total cases |
|---|---:|---:|---:|
| `examples/example_fifo` | 4 | 7 | 28 |
| `fpga/reg_handshake` | 3 | 3 | 9 |
| **Total** | **7 runs** | | **37** |

Lint (verilator `-Wall`, every module as its own top) passes with zero waivers.

### ECP5 resource usage — PASSED

Target **LFE5U-45F-7TG144C**, mapped with `yosys synth_ecp5`.

| Module | LUTs | FFs | EBRs | DSPs | LUT budget |
|---|---:|---:|---:|---:|---:|
| `examples/example_fifo` | 46 | 13 | 0 | 0 | 70 |
| `fpga/reg_handshake` | 11 | 10 | 0 | 0 | 200 |

Against the device: **44 000 LUTs, 108 EBRs, 72 DSPs**, with a 75 % ceiling on
the summed budgets.

This is 0.1 % of the part. It is a working harness, not a working payload — the
real consumers are `CMP-01` (CCSDS 123 predictor, est. 4000–7000 LUTs plus
10–20 EBRs and 6–12 DSPs) and `MEM-01` (DDR3 controller, est. 3000–5000 LUTs).
Those two plus the entropy coder are roughly 80 % of the LUT budget and none of
them exists yet.

---

## Cross-module spec checks — PASSED

```bash
python3 scripts/check_logic_spec.py --module <name>
```

`power`, `fpga`, `uart_io`, `camera`, `supervisor` — all five pass.

They verify drive-vs-receive levels and domain crossings across `io_specs/`.
Note what that does **not** mean: `camera.yaml` and `supervisor.yaml` are
skeletons whose electrical figures are almost entirely `PLACEHOLDER`, so these
checks are currently confirming that our placeholders are self-consistent. They
become meaningful the moment real transcribed numbers replace them — and they
are designed to fail loudly at that point if the real numbers conflict, which is
the whole reason the placeholder files are checked in.

---

## Known failing

### `kicad-ci / power / Schematic ERC` — 13 errors

Red since `6e3ef16` made ERC a real gate in August. `hardware/devboard.kicad_sch`
has no electrical connectivity: eleven pins sit off-grid so no wire endpoint
lands on a pin, and there are no `PWR_FLAG` symbols on the externally-supplied
rails. It is also still a 12-symbol barrel-jack/LDO placeholder that predates the
ECP5 retarget, so it does not contain the FPGA, camera or supervisor the io_specs
describe. Tracked in **#38 (H-01)**.

### `main` is unmergeable, for an unrelated reason

The `Baseline` ruleset requires status checks named `Schematic ERC` and
`Power rail SPICE verification`; `3b9b4f6` renamed those jobs to
`power / Schematic ERC` and `power / SPICE sweep verification`. The required
contexts no longer exist, so they can never report and every PR shows `BLOCKED`
whatever CI says. Also in **#38**.

---

## Open items by weight

| | |
|---|---|
| Blocks the most RTL | **#33** CCSDS 123 golden model — gates all four compression issues, the full-chain bench, #16 and #23. Unblocked today. |
| Blocks the PCB | **#13** camera interface. The client said Camera Link or GigE; the io_specs still describe a parallel bus. GigE would add a PHY, magnetics and a connector. PCB layout is due in January. |
| Invalidates the numbers above | **#14** confirm 45F resources and re-run the power budget on 45F static currents. |
| Blocks the firmware contract | **#17** freeze the CSR map. |
