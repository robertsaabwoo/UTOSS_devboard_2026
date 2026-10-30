# `rtl/examples/`

| File | What it is |
|---|---|
| [`fifo.v`](fifo.v) | **The FIFO exercise.** Ports and spec only; you write the inside. |
| [`reg_handshake.v`](reg_handshake.v) | A trivial register the harness uses as its self-test. Read it for the shape of a module and its bench. |

Neither is part of the payload design.

---

## The FIFO exercise

Write a synchronous FIFO in [`fifo.v`](fifo.v) that passes the tests in
[`rtl_tests/examples/fifo/`](../../rtl_tests/examples/fifo/). The spec is in the
module header. Read it before writing anything: the read-timing rule
(`rd_data` is valid before `rd_en`) is the one people miss.

### 1. Set up (once)

- Install **Docker Desktop** and start it. Wait until it says it is running.
- Install **Git**. On Windows, also install `make` (`winget install
  ezwinports.make`), or skip make and use `tools\dev.cmd` in place of
  `make` below.
- Clone the repo and open a terminal in it.

### 2. See it fail

```bash
make sim ARGS="--only fifo"
```

The first run builds the toolchain container (a few minutes, once). Then each
size of FIFO (8x16, 1x2, 32x8) runs 6 tests, and against the empty module they
show as `not done yet (exercise)` with the reason for each failure. That is
expected: there is nothing in the module yet.

### 3. Write it

Delete the PLACEHOLDER block in `fifo.v` and write the FIFO. Rerun
`make sim ARGS="--only fifo"` as often as you like. Each failure says what went
wrong, e.g. `the write while full overwrote stored data`. Fix the first failure
first: later ones often follow from it.

You do not need to touch `bench.yaml` or the test file.

### 4. Look at it

```bash
make waves ARGS="--only fifo --param-set minimal"
```

This prints the path of an `.fst` waveform. Open it at
<https://app.surfer-project.org/> (nothing to install) or in GTKWave.

### 5. Measure it

```bash
make synth ARGS="--only fifo"
```

This reports how many LUTs and flip-flops your FIFO costs on the Kria K26. Try
resetting the memory array in a loop and compare: that turns the memory into
flip-flops.

### Done

Every run says `pass`, and `make lint` is clean. If something will not pass
and you cannot see why, the waveform usually shows it within a few cycles of
the first failing read.

---

## `reg_handshake`

[`reg_handshake.v`](reg_handshake.v) is one register with a busy/ack handshake,
and its bench is
[`rtl_tests/examples/reg_handshake/`](../../rtl_tests/examples/reg_handshake/).
It exists so the harness always has a passing bench to run, and CI's waveform
check uses it. Its [`bench.yaml`](../../rtl_tests/examples/reg_handshake/bench.yaml)
documents every field inline.

To see a failure, drop the `!busy` from its write condition and run
`make sim ARGS="--only reg_handshake"`. Restore it with
`git checkout -- rtl/examples/reg_handshake.v`.

## Writing a real module

The payload modules, and their tests, are yours to write. Start one with

```bash
tools/dev new fpga <name>
```

and follow the conventions in [`../README.md`](../README.md).
