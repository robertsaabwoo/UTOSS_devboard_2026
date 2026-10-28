# `rtl/examples/`

One module lives here: [`reg_handshake.v`](reg_handshake.v), a single register
with a busy/ack handshake. Its bench is
[`rtl_tests/examples/reg_handshake/`](../../rtl_tests/examples/reg_handshake/).

It is **not part of the payload design** and not a starting point for any
issue. It is deliberately trivial, and exists for two reasons:

- **The harness needs something to run.** CI treats "no benches found" as a
  failure, so there is always at least one bench, and the waveform check uses
  it too.
- **It shows the shape of things.** A module, a `bench.yaml` with a parameter
  sweep and a budget, and a cocotb test file that checks reset, a normal write
  and one misuse case. [`bench.yaml`](../../rtl_tests/examples/reg_handshake/bench.yaml)
  documents every field inline.

The payload modules, and their tests, are yours to write. Start one with

```bash
tools/dev new fpga <name>
```

and follow the conventions in [`../README.md`](../README.md), which the linter
enforces whether or not this example follows them.

## Try it

```bash
make sim   ARGS="--only reg_handshake"
make waves ARGS="--only reg_handshake --param-set narrow"
make synth ARGS="--only reg_handshake"
```

To see a failure, break something in `reg_handshake.v`, for example drop the
`!busy` from the write condition, and run `make sim` again. Restore it with
`git checkout -- rtl/examples/reg_handshake.v`.
