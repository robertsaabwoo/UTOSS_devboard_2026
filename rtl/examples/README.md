# Worked example — `example_fifo`

A complete, finished module and bench, here to be read and to be demoed. It is
the shortest honest answer to "what does a module in this repo look like, and
what does it take to land one?"

| | |
|---|---|
| Module | [`example_fifo.v`](example_fifo.v) |
| Manifest | [`../../rtl_tests/examples/example_fifo/bench.yaml`](../../rtl_tests/examples/example_fifo/bench.yaml) |
| Bench | [`../../rtl_tests/examples/example_fifo/test_example_fifo.py`](../../rtl_tests/examples/example_fifo/test_example_fifo.py) |
| Measured | 46 LUTs, 13 FFs, 0 EBR, 0 DSP at `WIDTH=8, DEPTH=16` |
| Status | 7 tests × 4 parameter sets = 28 cases, all green |

```bash
tools/dev sim   --module examples     # 4 parameter sets
tools/dev lint  --only example_fifo
tools/dev synth --only example_fifo
```

On Windows, the same three with `tools\dev.cmd` in place of `tools/dev`.
Invoking `tools\dev.ps1` directly fails on a default install — see
`rtl_tests/README.md`.

**This is not `I-01`.** Issue I-01 asks for `rtl/fpga/common/fifo_sync.v` with
sticky overflow and underflow flags and a high-water mark feeding the CSR
telemetry — because on a payload that images for one to two minutes a day, a
dropped sample nobody hears about is worse than a crash. None of that is here.
Read the issue; don't copy this file into `rtl/fpga/common/` and call it done.

---

## The loop this demonstrates

1. `tools/dev new fpga my_block` — scaffolds module, manifest and bench, all
   already passing.
2. Write the RTL. Run `tools/dev lint` early and often; it is seconds, and it
   catches the width and latch mistakes that otherwise surface as a confusing
   simulation failure minutes later.
3. Write the bench against a **reference model**, not hand-written expected
   values.
4. `tools/dev synth` once it elaborates, and put the **measured** number into
   `synth.budget`.
5. Flip `status: wip` → `ready`, open the PR.

Nothing in that list involves touching a CI file.

---

## Three things in here worth copying

**The parameter sweep is the test.** Four sets: `default` (8×16), `minimal`
(1×2 — smallest legal everything), `narrow_odd` (3×7 — *not* a power of two),
and `wide` (32×64). The bench calls `assert_param` so a parameter override that
silently failed to apply is a failure rather than three identical passes.

**A reference model beats expected values.** `test_random_traffic_against_
reference_model` runs 2000 randomized operations against a Python `deque`,
checking `level`, `full`, `empty` and the head on every single step. A
hand-written expectation can only cover what you already thought of.

**Boundaries get walked, not sampled.**
`test_concurrent_rw_at_every_level` asserts a simultaneous read and write at
*every* occupancy from 0 to DEPTH. Random traffic wanders near those points but
will not reliably hit "read and write on the same edge while exactly full",
which is precisely where FIFO off-by-ones live.

---

## Demo: break it and watch the gates catch it

Each of these is a one-line edit to `example_fifo.v` with the real, verified
output. Restore with `git checkout -- rtl/examples/example_fifo.v` between
each.

### 1. The bug that only one parameter set can see — *the best one*

Make the write pointer free-run instead of wrapping at `LAST_ADDR`:

```verilog
// was: wr_ptr <= (wr_ptr == LAST_ADDR) ? {ADDR_W{1'b0}} : wr_ptr + ADDR_ONE;
       wr_ptr <= wr_ptr + ADDR_ONE;
```

```
tools/dev sim --only example_fifo

| examples/example_fifo | default    | pass | 7 |
| examples/example_fifo | minimal    | pass | 7 |
| examples/example_fifo | narrow_odd | FAIL | 7 | step 23: oldest entry reads 0x3, model says 0x4
| examples/example_fifo | wide       | pass | 7 |
3 passed, 1 failed
```

**Three of four parameter sets pass.** A free-running counter wraps correctly
whenever DEPTH is a power of two, so 16, 2 and 64 are all happy and only
`DEPTH=7` notices. Test this module at its default width only — which is what
a single-configuration bench does — and this ships.

### 2. The simultaneous read/write off-by-one

```verilog
// was: end else if (do_rd && !do_wr) begin
       end else if (do_rd) begin
```

```
| examples/example_fifo | default | FAIL | 7 | test_concurrent_rw_at_every_level:
  concurrent read+write at occupancy 1 changed level to 0 -- the simultaneous
  case is miscounted, which will drift the FIFO's idea of its own fullness
  over a long capture
```

Caught at occupancy 1, immediately, by the exhaustive walk.

### 3. An overflow that destroys queued data

```verilog
// was: wire do_wr = wr_en && !full;
       wire do_wr = wr_en;
```

```
| examples/example_fifo | default | FAIL | 7 | test_write_while_full_is_dropped_
  not_destructive: FIFO accepted a write while reporting full; ...
```

The one that matters most on this payload: a FIFO that overwrites its oldest
entry under pressure loses data with **no symptom at all**. The capture reports
success and the cube is wrong, and it cannot be re-taken.

### 4. Blow the area budget

Not a code change — edit `bench.yaml` and set `synth.budget.luts: 20`:

```
tools/dev synth --only example_fifo

Target: LFE5U-45F-7TG144C  (ECP5 (LFE5U -- no SERDES), TQFP-144)
[FAIL] examples/example_fifo  LUTs 46  FFs 13  EBRs 0  DSPs 0
LUTs: 46 used against a budget of 20 (+26). Either optimise, or raise
synth.budget.luts in bench.yaml and say in the pull request what the extra
area bought.
```

Those are real ECP5 cells from `yosys synth_ecp5`, not an estimate.

---

## The memory-inference point

`rd_data` is an **asynchronous** read of `mem`, so yosys infers distributed LUT
RAM — which is why the measured result is 46 LUTs and **0 EBRs**, and why
`block_ram_blocks: 0` in the manifest is a real assertion rather than a
formality.

That is the right choice at these depths and the wrong one at, say,
`DEPTH=1024, WIDTH=32`: 32 kbit in LUTs costs roughly a hundred times what the
same buffer costs in one of the 45F's 108 EBRs. The real `fifo_sync` in `I-01`
has to infer EBR when it is large, and `tools/dev synth` is how you find out
which one you actually got. A 2 kB buffer that quietly became 16 000 LUTs is a
classic way to run out of an FPGA in March.
