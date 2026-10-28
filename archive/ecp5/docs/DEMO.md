# Demoing the RTL verification harness

A 10-minute walkthrough. The point to land is not "we have tests" — it is **"the
gates actually catch things, and adding a module costs one command."** So most of
the time goes on Act 2, where things deliberately fail.

Rehearse it once end to end before doing it live. Every command below has been run
and its real output is quoted.

---

## Pre-flight — do this BEFORE the audience arrives

**1. Docker Desktop must be running.** Check:

```powershell
docker version --format '{{.Server.Version}}'
```

If it errors, launch Docker Desktop and wait ~30 s.

**2. Pre-build the image.** It is ~1.0 GB and takes several minutes. Do not do this
live.

```powershell
cd C:\Users\there\Desktop\devboard\UTOSS_DEVBOARD_2026
git checkout feature/rtl-verification-harness
$env:UTOSS_PIP_TRUSTED_HOST = "pypi.org files.pythonhosted.org"
tools\dev.cmd build
```

> **The `UTOSS_PIP_TRUSTED_HOST` line is required on the UofT network.** It
> re-signs HTTPS, so `pip` inside the build rejects pypi.org with
> `CERTIFICATE_VERIFY_FAILED` even though `apt` works. Without it the build fails
> at the cocotb step. It is off by default so CI verifies certificates normally.

**3. Confirm green, and confirm the working tree is clean.** Act 2 edits files, so
you need a clean baseline to restore to.

```powershell
tools\dev.cmd all
git status --short      # must be empty
```

Expect `RTL SIMULATION PASSED` and `SYNTH CHECK PASSED`.

**4. Have these two tabs open:**
- https://github.com/robertsaabwoo/UTOSS_devboard_2026/pull/37
- https://github.com/robertsaabwoo/UTOSS_devboard_2026/issues

> **Why `tools\dev.cmd` and not `tools\dev.ps1`.** A fresh Windows shell has
> every PowerShell execution-policy scope `Undefined`, which means `Restricted`,
> so `.\tools\dev.ps1` fails outright with `UnauthorizedAccess: running scripts
> is disabled on this system`. The `.cmd` wrapper is not a PowerShell script, so
> it runs regardless, and it bypasses the policy for that one child process
> only -- nothing on the machine changes. Do not try to fix this with
> `Set-ExecutionPolicy` five minutes before a demo.
>
> Using Git Bash or WSL instead? Every `tools\dev.cmd` below becomes
> `tools/dev`, and `make sim` / `make all` also work. All three run the same
> container.

---

## Act 1 — the toolchain is one command (1 min)

```powershell
tools\dev.cmd versions
```

```
Icarus Verilog version 12.0 (stable)
Verilator 5.020 2024-01-01
Python 3.12.3
cocotb 1.9.2
Yosys 0.33
"nextpnr-ecp5" -- Next Generation Place and Route (Version 0.6-3build5)
```

**Say:** nobody installs any of that. It is one container, built from the repo, and
CI runs the identical image — so "works on my machine" stops being a conversation.

```powershell
tools\dev.cmd list
```

```
fpga       reg_handshake ready    [default, narrow, wide]  rtl_tests/fpga/reg_handshake
1 bench manifest(s) validated.
```

**Say:** CI discovers benches. There is no list to add yourself to.

---

## Act 2 — the gates actually catch things (5 min, the important part)

Four deliberate breakages. **Run the restore command after each one** — they are
listed inline.

### 2a. A bug in a module the testbench covers

Open `rtl\fpga\reg_handshake.v`. Find:

```verilog
      if (wr_en && !busy) begin
```

Delete the `&& !busy`, so a held `wr_en` can re-latch data mid-transaction:

```verilog
      if (wr_en) begin
```

```powershell
tools\dev.cmd sim --only reg_handshake
```

```
| Bench                | Params  | Status | Tests | Time  | Detail                       |
| `fpga/reg_handshake` | default | FAIL   | 3     | 11.5s | test_held_wr_en_does_not_... |

0 passed, 3 failed, 0 wip-failed, 0 blocked

RTL SIMULATION FAILED:
  - fpga/reg_handshake[default]: test_reg_handshake.test_held_wr_en_does_not_corrupt_data:
    data_out re-latched while busy -- write handshake corrupted mid-transaction
    log: build/rtl/fpga/reg_handshake/default/sim.log
```

All three parameter sets fail, not just one — the bug is width-independent.

**Say:** that is the failure message the bench author wrote. Not "expected 60 got
255" — it says what the bug *means* for the design. That is the standard in
`rtl/README.md`.

**Restore:** `git checkout -- rtl/fpga/reg_handshake.v`

### 2b. An inferred latch in a module nothing instantiates yet

This is the one worth dwelling on. Create `rtl\fpga\common\demo_latch.v`:

```verilog
module demo_latch (input wire a, output reg y);
  always @(*) if (a) y = 1'b1;
endmodule
```

Add it to `rtl_tests\fpga\reg_handshake\bench.yaml` under `sources:`

```yaml
sources:
  - rtl/fpga/reg_handshake.v
  - rtl/fpga/common/demo_latch.v
```

```powershell
tools\dev.cmd lint
```

```
%Warning-LATCH: /work/rtl/fpga/common/demo_latch.v:2:3: Latch inferred for
signal 'y' (not all control paths of combinational always assign a value)
LINT FAILED
```

**Say:** `demo_latch` is not instantiated anywhere. A normal lint setup elaborates
only the declared top, so it would parse this file and say nothing — and the
not-yet-integrated module is exactly the one most likely to have the bug. This
harness lints every file as its own top. An ECP5 has no latches worth using; what
you get instead is a routing-dependent timing hazard that simulates perfectly.

**Restore:** `git checkout -- rtl_tests/fpga/reg_handshake/bench.yaml` then
`Remove-Item rtl\fpga\common\demo_latch.v`

### 2c. An RTL file with no testbench at all

```powershell
Copy-Item rtl\fpga\reg_handshake.v rtl\fpga\common\orphan.v
tools\dev.cmd lint
```

```
LINT FAILED: RTL files not compiled by any bench:
  - rtl/fpga/common/orphan.v
Every module needs a bench.
```

**Say:** an untested module cannot exist quietly. You cannot land Verilog here
without a bench.

**Restore:** `Remove-Item rtl\fpga\common\orphan.v`

### 2d. Blowing the resource budget

In `rtl_tests\fpga\reg_handshake\bench.yaml`, change `luts: 200` to `luts: 5`:

```powershell
tools\dev.cmd synth
```

```
Target: LFE5U-45F-7TG144C  (ECP5 (LFE5U -- no SERDES), TQFP-144)
[FAIL] fpga/reg_handshake  LUTs 11  FFs 10  EBRs 0  DSPs 0
SYNTH CHECK FAILED:
LUTs: 11 used against a budget of 5 (+6). Either optimise, or raise
synth.budget.luts in bench.yaml and say in the pull request what the extra
area bought.
```

**Say:** yosys mapped it to real ECP5 cells on the 45F, so these are honest
numbers. Every module declares a budget, and the sum of all budgets is held
against 75 % of the device. The reason that matters: `RTL_PLAN.md` estimates the
compressor plus the DDR3 controller at 8–15k LUTs, and the part is 44k. We find
out we are running out while there is still time to change the architecture —
not in April.

**Restore:** `git checkout -- rtl_tests/fpga/reg_handshake/bench.yaml`

### Confirm you are back to clean

```powershell
git status --short      # must be empty
tools\dev.cmd all     # green again
```

---

## Act 3 — adding a module is one command (2 min)

```powershell
tools\dev.cmd new fpga demo_block
```

```
created:
  rtl/fpga/demo_block.v
  rtl_tests/fpga/demo_block/bench.yaml
  rtl_tests/fpga/demo_block/test_demo_block.py
```

```powershell
tools\dev.cmd sim --only demo_block
```

```
[run]     fpga/demo_block[default] (wip)
          -> pass  2 test(s)
[run]     fpga/demo_block[narrow] (wip)
          -> pass  2 test(s)
RTL SIMULATION PASSED
```

**Say:** three files, already running, no CI edits. It is scaffolded green on
purpose — a scaffold that starts red teaches people to ignore red.

Then show the `wip` guard, which is the bit people ask about:

```powershell
tools\dev.cmd sim --strict
```

```
STRICT: these benches are still status: wip and cannot be merged into main:
  - rtl_tests/fpga/demo_block/bench.yaml
```

**Say:** `wip` lets a half-written module live on your branch without turning CI
red. A PR into `main` runs `--strict`, where `wip` is itself a failure — so "wip"
cannot quietly become permanent.

One more, if asked how we know the parameter sweeps are real. Open
`rtl_tests\fpga\reg_handshake\bench.yaml` and change the `wide` set's
`WIDTH: 64` to `WIDTH: 63`, then:

```powershell
tools\dev.cmd sim --only reg_handshake --param-set wide
```

It still passes — now change `toplevel:` to a typo instead and it fails with
*"the simulation produced no result file"*. The point: `assert_param` compares
what `bench.yaml` asked for against what the DUT actually elaborated to, so a
dropped `-P` flag fails instead of running the default width three times and
reporting three passes.

**Restore:** `git checkout -- rtl_tests/fpga/reg_handshake/bench.yaml` and
`Remove-Item -Recurse rtl\fpga\demo_block.v, rtl_tests\fpga\demo_block`

---

## Act 4 — where the team starts (2 min)

Switch to the browser.

**Issues tab** — 34 issues, filter by label:
- `decision` (5) — #13 camera interface, #14 the 45F reconciliation, #15 cube
  layout, #16 SPI vs SDIO, #17 the CSR map. Each blocks RTL and none was written
  down anywhere before.
- `good-first-issue` (4) — start people here.
- `P0` (18) — the critical path.

Open **#24 (CDC primitives)** and scroll it. **Say:** this is what every issue
looks like — the port list, numbered requirements, a resource budget, and named
acceptance criteria. The acceptance criteria are written as *the tests that must
exist*, because "verified" with no named cases is how a module passes against a
bench that only walks the happy path.

Then open **#33 (CCSDS golden model)**. **Say:** this is the highest-leverage
thing open. It gates all four compression issues, the full-chain bench, the SD
decision and sensor correction — and it is Python, needs no hardware decision,
and is unblocked today.

**PR #37** — 76 files. Point at the checks: `rtl-ci` green, `kicad-ci / power /
Schematic ERC` red. **Say:** that red one is issue #38 — the schematic is still a
12-symbol placeholder with no real connectivity, which predates the ECP5
retarget. The gate is working; it is telling us the truth about the hardware side.

---

## Closing line

> Fourteen modules, one contract: drop a `bench.yaml` and a testbench in a
> directory and it runs. The gates refuse a latch, an untested file, a blown area
> budget, and a test that silently tested nothing. The work is specified down to
> port lists and acceptance criteria. Pick an issue.

---

## If something goes wrong live

| Symptom | Fix |
|---|---|
| `docker not found` / pipe error | Docker Desktop is not running. Launch it, wait 30 s. |
| Build fails in `pip`, `CERTIFICATE_VERIFY_FAILED` | `$env:UTOSS_PIP_TRUSTED_HOST = "pypi.org files.pythonhosted.org"`, rebuild. |
| A gate fails unexpectedly | `git status --short` — a restore step from Act 2 was missed. `git checkout -- .` and delete stray files under `rtl/fpga/common/`. |
| Everything is slow | The image is building. You skipped pre-flight step 2. |
| Need to skip the container entirely | `$env:UTOSS_NO_DOCKER = "1"` uses tools from PATH — only if they are installed. |
