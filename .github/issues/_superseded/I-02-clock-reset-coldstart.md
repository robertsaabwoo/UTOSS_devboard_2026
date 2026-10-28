---
id: I-02
title: "RTL: clock/reset infrastructure and cold-start sequencer (EHXPLLL, POR, ready handshake)"
labels: [rtl, P0, "area:infrastructure", "size:M"]
depends_on: [I-01, D-02]
---

## What

The clock and reset block, and the cold-start FSM that brings the payload from
"rails just came up" to "ready for a capture command".

## Why the sequencing is a design item and not boilerplate

The FPGA is **power-gated** (`io_specs/power.yaml`, gated rails; the supervisor
owns `FPGA_PWR_EN`). So every imaging pass is a genuine cold start:
configuration load from the supervisor → PLL lock → DDR3 init and calibration →
ready flag back to the supervisor. Any of those can fail, and when one does the
supervisor needs to be told **which**, because its only recovery options are
"reconfigure" and "power-cycle" and they are not interchangeable.

A design that merely assumes everything locked eventually will, sooner or later,
start a capture against an uncalibrated DDR3 and write a cube of garbage that
cannot be re-taken.

## Deliverables

- `rtl/fpga/common/pll_sys.v` — `EHXPLLL` wrapper for the system domain
- `rtl/fpga/common/pll_ddr.v` — `EHXPLLL` wrapper for the DDR domain (may be
  subsumed by litedram's own PLL — check `MEM-01` before writing it)
- `rtl/fpga/clk_rst.v` — top-level clock/reset/POR block
- `rtl/fpga/coldstart_fsm.v` — the bring-up sequencer
- A bench per module, plus a simulation stub for `EHXPLLL` (see below)
- An FSM state diagram committed as `docs/FSM_COLDSTART.md` — **the client asked
  for FSM diagrams explicitly**, so this is a deliverable, not documentation debt

## Interfaces

```verilog
module clk_rst #(
    parameter integer SYS_MHZ = 100,
    parameter integer POR_CYCLES = 1024     // on the raw input clock
) (
    input  wire clk_in,          // board oscillator
    input  wire rst_in_n,        // external/supervisor reset, async, may float

    output wire clk_sys,
    output wire rst_sys_n,
    output wire clk_ddr,
    output wire rst_ddr_n,
    output wire clk_px_buf,      // camera clock, buffered -- NOT from a PLL
    output wire rst_px_n,
    output wire clk_sd,
    output wire rst_sd_n,

    input  wire clk_px_in,       // source-synchronous from the camera

    output wire pll_sys_locked,
    output wire pll_ddr_locked,
    output wire por_done
);

module coldstart_fsm (
    input  wire clk_sys,
    input  wire rst_sys_n,

    // Status in
    input  wire pll_sys_locked,
    input  wire pll_ddr_locked,
    input  wire ddr_init_done,       // from MEM-01
    input  wire ddr_cal_ok,
    input  wire csr_soft_reset,      // from C-01

    // Out
    output wire payload_ready,       // to the supervisor, and gates DP-*/CMP-*
    output wire [3:0] state,         // mirrored into the CSR status register
    output wire [3:0] fail_code,     // WHICH step failed -- see requirement 4
    output wire       fail_valid
);
```

## Behaviour requirements

1. **Reset distribution**: one `reset_sync` (`I-01`) per clock domain, fed from
   POR OR'd with the external reset. No reset crosses a domain unsynchronized.
   No domain's reset releases before its clock is running.
2. `rst_in_n` must be treated as potentially floating or noisy — the supervisor
   may be unprogrammed. Synchronize and debounce it; do not let a glitch on it
   reset a capture in progress without that being visible in the CSR.
3. **The camera clock is not ours.** `clk_px_in` comes from the sensor
   source-synchronously. It may be absent entirely (camera unpowered, camera not
   yet commanded to stream). The `px` domain reset must therefore not deadlock
   waiting for a clock that never arrives, and the absence of `clk_px` must be
   **detectable** — a watchdog counter in `clk_sys` that reports "no pixel clock"
   rather than a payload that sits silently in a state nobody can name.
4. **Every failure has a distinct `fail_code`**, latched with `fail_valid`, and it
   is readable over the CSR. At minimum: sys PLL no lock, DDR PLL no lock, DDR
   init timeout, DDR calibration failed, no pixel clock. "It did not come up" is
   not a diagnosis the supervisor can act on.
5. Every wait state has a **timeout**. A bring-up FSM that waits forever for a
   lock that will never come is a payload that draws power until the next
   power-cycle and reports nothing. On timeout: latch `fail_code`, enter a defined
   failed state, keep the CSR readable.
6. `payload_ready` asserts only when every step has succeeded, and deasserts on
   soft reset or on any subsequent failure. Downstream blocks hold reset until it
   asserts.
7. `default:` arm on the state machine returns to a safe state (`rtl/README.md`
   §4). This FSM is a TMR candidate in `C-05` — an upset that parks it in an
   unreachable state bricks the payload for the pass.
8. `EHXPLLL` instances live **only** inside the wrapper modules, with a plain
   Verilog interface, so the rest of the design stays simulatable in Icarus
   (`rtl/README.md` §7).

## Simulating EHXPLLL

Icarus cannot elaborate the Lattice primitive. Provide
`rtl_tests/common/stubs/EHXPLLL.v`: a behavioural model that divides/multiplies
with a `#delay` and asserts `LOCK` after a configurable number of cycles,
including the ability to **never** lock, so requirement 5 is testable. Include it
in the bench `sources` but **not** in the synthesis `sources` — use a bench-only
source list, and confirm with `tools/dev synth` that the real primitive is what
gets mapped.

## Resource budget

Expect under 300 LUTs and 200 FFs for `clk_rst` plus `coldstart_fsm`, excluding
the PLLs themselves. Set `synth.budget` from a measured run.

## Acceptance criteria

- Bench shows reset asserting in every domain within one cycle of POR, and
  releasing only after that domain's clock is running and its PLL has locked.
- For each failure mode in requirement 4, a test that forces it and asserts the
  exact `fail_code`, and that `payload_ready` stays low.
- A test where `clk_px_in` **never** toggles: the design reaches a defined state,
  reports "no pixel clock", and the CSR remains readable.
- A test where a PLL never locks: timeout fires, `fail_valid` asserts,
  `payload_ready` stays low, no deadlock.
- Reset asserted mid-bring-up restarts the sequence cleanly from the beginning.
- `docs/FSM_COLDSTART.md` contains the state diagram with every transition and
  every timeout labelled.
- `tools/dev synth` maps `EHXPLLL` (not the stub), and reports PLL usage within
  the count confirmed in `D-02`.

## References

- `rtl/RTL_PLAN.md` §12
- `io_specs/power.yaml` (gated rails, bring-up sequence),
  `io_specs/fpga.yaml` (`VCCIO_BANK8` POR behaviour, section 3.5)
- `io_specs/supervisor.yaml` (`FPGA_PWR_EN`, `CFG_BUS`)
- `UTAT Meeting.txt`: "they want an FSM diagram"; "will need an image of the CPU
  and FPGA for startup"
