# Running and writing RTL tests

**The whole contract: drop a directory containing a `bench.yaml` and a cocotb
testbench under `rtl_tests/<module>/<name>/`, and it runs — locally and in CI.**
There is no CI file to edit, no list to add yourself to, and no Makefile to
write.

---

## Running things

Everything runs inside the container from [`../docker/`](../docker/README.md),
which is the same image CI uses. First run builds it (a few minutes); after that
it is cached.

> **Windows: use `tools\dev.cmd`, not `tools\dev.ps1` directly.** A fresh
> Windows shell has every PowerShell execution-policy scope set to `Undefined`,
> which means `Restricted`, so `.	ools\dev.ps1` fails with
> `UnauthorizedAccess: running scripts is disabled on this system`. The `.cmd`
> wrapper is not a PowerShell script, so it runs regardless, and it launches
> `dev.ps1` with a bypass scoped to that one child process — no machine or user
> setting is changed.
>
> In Git Bash or WSL, use `tools/dev` (or `make sim` / `make all`). All three
> wrappers run the same container.

```bash
tools/dev all                      # lint + simulate + synthesise: what CI runs
tools/dev sim                      # every bench
tools/dev sim --only dcmi_rx       # one bench
tools/dev sim --only dcmi_rx --param-set narrow
tools/dev sim --waves              # keep waveforms under build/rtl/...
tools/dev sim --verbose            # stream simulator output
tools/dev lint                     # verilator lint over all RTL
tools/dev synth                    # ECP5 mapping + resource budgets
tools/dev list                     # every discovered bench and its status
tools/dev shell                    # poke around inside the container
```

`make sim`, `make lint`, `make synth`, `make all` do the same thing. On Windows
without Git Bash or WSL, use `.\tools\dev.ps1 sim`.

Outputs land in `build/` (git-ignored): `results.xml`, `sim.log` and the
waveform per bench and parameter set, `yosys.log` and the netlist per synthesis
run, and a `summary.md` for each.

**Without Docker:** set `UTOSS_NO_DOCKER=1` and the same commands use
`iverilog`, `verilator`, `yosys` and `cocotb` from your `PATH`. Faster in a tight
loop; a version difference from CI is then yours to debug. `tools/dev versions`
prints what the container has.

**If the image build fails in `pip` with `CERTIFICATE_VERIFY_FAILED`** you are on
a network that re-signs HTTPS. Set
`UTOSS_PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org"` and build again.

---

## `bench.yaml`

The fully-documented example is
[`fpga/reg_handshake/bench.yaml`](fpga/reg_handshake/bench.yaml). Field
reference:

| Field | Required | Meaning |
|---|---|---|
| `name` | no | Label in logs and summaries. Defaults to the directory name. |
| `status` | no | `ready` (default), `wip` or `blocked`. See below. |
| `blocked_reason` | if blocked | Why. A bench switched off without a stated reason stays off forever. |
| `toplevel` | **yes** | Verilog module instantiated as the simulation top. |
| `testbench` | **yes** | Python module in this directory holding the `@cocotb.test()` coroutines. |
| `sources` | **yes** | Repo-relative Verilog paths, globs allowed, headers first. |
| `param_sets` | no | List of `{name, params}`. The bench is run once per entry. Defaults to one empty set. |
| `timeout_seconds` | no | Wall-clock limit per parameter set (default 300). A hung simulation is a failure. |
| `simulator` | no | `icarus` (default) or `verilator`. |
| `defines` | no | Preprocessor defines. |
| `lint.enabled` | no | Default true. |
| `lint.waivers` | no | Verilator warning codes to waive. Each needs a reason, and will be argued about in review. |
| `synth.enabled` | no | Default true. |
| `synth.top` | no | Defaults to `toplevel`. |
| `synth.param_set` | no | Which parameter set to measure area with. |
| `synth.budget` | no | `luts`, `ff`, `block_ram_blocks`, `dsp_mult_18x18`. CI fails if the mapped design exceeds it. |
| `synth.place` | no | Run nextpnr place-and-route. Top level only. |
| `synth.lpf` | if placing | Pin constraint file. |
| `synth.target_mhz` | no | Timing target passed to nextpnr. |

Unknown keys are **rejected**, not ignored. A typo that silently disables a
bench looks exactly like a passing build, which is the one failure mode this
harness exists to prevent.

### `status`

| | Runs? | Failure is fatal? |
|---|---|---|
| `ready` | yes | yes — everywhere |
| `wip` | yes | on a feature branch, no (reported loudly); on a pull request into `main`, **yes**, and `wip` itself fails |
| `blocked` | no | n/a — listed in the summary with its reason |

So `wip` lets a half-written module live on a branch without turning CI red, and
cannot leak into `main`.

---

## Writing a bench

Scaffold it:

```bash
tools/dev new fpga dcmi_rx
```

That writes `rtl/fpga/dcmi_rx.v`, `rtl_tests/fpga/dcmi_rx/bench.yaml` and
`rtl_tests/fpga/dcmi_rx/test_dcmi_rx.py`, all of which already pass. Then read
[`fpga/reg_handshake/test_reg_handshake.py`](fpga/reg_handshake/test_reg_handshake.py)
— it is the worked example.

### Shared helpers

`rtl_tests/common/utoss_tb/` is on `PYTHONPATH` automatically:

```python
from utoss_tb import (
    start_clock,            # start a clock on dut.<port>
    reset_active_low,       # the repo reset convention
    width_of,               # width of a DUT signal, for width-generic benches
    assert_param,           # check the DUT elaborated at the requested parameter
    StreamSource,           # drive a *_tdata/_tvalid/_tready interface
    StreamSink,             # collect from one, with backpressure
    check_stream_protocol,  # background checker for stream rules R2/R3
)
```

### Four things that make a bench worth having

1. **Stay width-generic.** The runner replays your bench at every `param_set`,
   so nothing may hard-code a width or a literal that only fits one of them. Use
   `width_of(...)` and mask your test vectors. Call
   `assert_param("WIDTH", width_of(dut.some_port))` once, so a parameter
   override that silently failed to apply is a failure rather than three
   identical passes.

2. **Assert the failure that would actually hurt.** A test that only walks the
   happy path passes against a broken DUT. For this payload that means: what
   happens on a short or malformed frame, when a FIFO fills, when a transfer is
   stalled mid-beat, when reset arrives mid-transaction, when a counter wraps.
   The imaging pass is one to two minutes a day and cannot be re-taken — a
   silent corruption is worse than a crash.

3. **Apply backpressure and gaps.** `StreamSource(..., backpressure=0.3)` and
   `StreamSink(..., backpressure=0.3)` in at least one test. A module that has
   only ever seen a gapless source and an always-ready sink is untested against
   the real DDR arbiter and CDC FIFO.

4. **Say what a failure means.** Assertion messages are read by whoever broke
   the build six weeks from now, and "expected 60 got 0" tells them nothing.
   Write "data_out re-latched while busy — write handshake corrupted
   mid-transaction".

### Running one bench by hand

The runner is the gate, but when you want raw simulator output:

```bash
tools/dev shell
cd rtl_tests/fpga/reg_handshake
make -f ../../common/cocotb.mk \
    TOPLEVEL=reg_handshake MODULE=test_reg_handshake \
    VERILOG_SOURCES=/work/rtl/fpga/reg_handshake.v
```

Note that `make` on its own **exits 0 even when testcases fail** — which is why
`scripts/run_rtl_tests.py` reads `results.xml` instead of trusting the exit code,
and why it treats "no testcases at all" as a failure too.
