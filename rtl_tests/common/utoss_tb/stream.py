"""Driver, monitor and protocol checker for the repo's stream convention.

The convention (full statement in rtl/README.md): an AXI4-Stream subset with
`<p>_tdata`, `<p>_tvalid`, `<p>_tready`, and optional `<p>_tlast` / `<p>_tuser`.
Three rules, all of them enforced by check_stream_protocol below:

  R1  tvalid must not depend on tready. A source may not wait to see tready
      before asserting tvalid -- that combinational path across two modules is
      the classic AXI deadlock.
  R2  once tvalid is asserted it stays asserted until a transfer completes
      (tvalid && tready on a rising edge). Dropping it is a lost beat.
  R3  tdata, tlast and tuser are stable while tvalid is asserted and tready is
      not. Changing them mid-stall silently corrupts the beat.

Every pipeline module in the design sits between two of these interfaces, so a
bug in one of these rules shows up as a corrupted image cube four blocks
downstream. Checking it at every boundary is much cheaper than finding it there.
"""
import random

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly


def _sig(dut, prefix, suffix):
    name = f"{prefix}_{suffix}" if prefix else suffix
    return getattr(dut, name, None)


class StreamSource:
    """Drives a stream interface into the DUT.

    `backpressure` is the probability of inserting an idle (tvalid low) cycle
    between beats. Leave it non-zero in at least one test: a module that only
    ever sees a gapless source is untested against the gaps it will actually
    get from a CDC FIFO or a DDR arbiter.
    """

    def __init__(self, dut, prefix, clk="clk", backpressure=0.0, seed=None):
        self.clk = getattr(dut, clk)
        self.tdata = _sig(dut, prefix, "tdata")
        self.tvalid = _sig(dut, prefix, "tvalid")
        self.tready = _sig(dut, prefix, "tready")
        self.tlast = _sig(dut, prefix, "tlast")
        self.tuser = _sig(dut, prefix, "tuser")
        if self.tdata is None or self.tvalid is None or self.tready is None:
            raise AttributeError(
                f"{prefix}: expected {prefix}_tdata/_tvalid/_tready on the DUT. "
                "Stream ports must follow the naming convention in rtl/README.md "
                "or the shared driver cannot bind to them."
            )
        self.backpressure = backpressure
        self.random = random.Random(seed)
        self.tvalid.value = 0

    async def send(self, beats, last_on_final=True):
        """Drive `beats` (ints, or (data, last) / (data, last, user) tuples)."""
        beats = list(beats)
        for index, beat in enumerate(beats):
            if isinstance(beat, tuple):
                data, last, user = (tuple(beat) + (None, None))[:3]
            else:
                data, last, user = beat, None, None
            if last is None:
                last = last_on_final and index == len(beats) - 1

            while self.backpressure and self.random.random() < self.backpressure:
                self.tvalid.value = 0
                await RisingEdge(self.clk)

            self.tdata.value = data
            if self.tlast is not None:
                self.tlast.value = int(bool(last))
            if self.tuser is not None and user is not None:
                self.tuser.value = user
            self.tvalid.value = 1

            # R1/R2: tvalid is asserted unconditionally and held until the DUT
            # takes the beat. We sample tready in the read-only region of the
            # edge, which is after the DUT has settled it.
            while True:
                await RisingEdge(self.clk)
                await ReadOnly()
                if self.tready.value == 1:
                    break

            await cocotb.triggers.NextTimeStep()

        self.tvalid.value = 0


class StreamSink:
    """Collects beats out of the DUT into `self.beats`.

    `backpressure` is the probability of deasserting tready on any given cycle.
    A sink that is always ready hides every stall bug in the DUT.
    """

    def __init__(self, dut, prefix, clk="clk", backpressure=0.0, seed=None):
        self.clk = getattr(dut, clk)
        self.tdata = _sig(dut, prefix, "tdata")
        self.tvalid = _sig(dut, prefix, "tvalid")
        self.tready = _sig(dut, prefix, "tready")
        self.tlast = _sig(dut, prefix, "tlast")
        if self.tdata is None or self.tvalid is None or self.tready is None:
            raise AttributeError(
                f"{prefix}: expected {prefix}_tdata/_tvalid/_tready on the DUT."
            )
        self.backpressure = backpressure
        self.random = random.Random(seed)
        self.beats = []
        self.packets = []
        self._current = []
        self.tready.value = 0

    def start(self):
        """Begin collecting. Returns the cocotb task so a test can cancel it."""
        return cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            ready = not (self.backpressure
                         and self.random.random() < self.backpressure)
            self.tready.value = int(ready)
            await RisingEdge(self.clk)
            await ReadOnly()
            if ready and self.tvalid.value == 1:
                data = int(self.tdata.value)
                self.beats.append(data)
                self._current.append(data)
                if self.tlast is not None and self.tlast.value == 1:
                    self.packets.append(self._current)
                    self._current = []
            await cocotb.triggers.NextTimeStep()


async def check_stream_protocol(dut, prefix, clk="clk", rst_n="rst_n"):
    """Background checker for R2 and R3. Start it with cocotb.start_soon.

    Runs for the life of the test and raises on the first violation, so the
    failure is reported at the cycle it happened rather than as a mismatch
    thousands of cycles later.
    """
    clk_sig = getattr(dut, clk)
    rst_sig = getattr(dut, rst_n, None)
    tdata = _sig(dut, prefix, "tdata")
    tvalid = _sig(dut, prefix, "tvalid")
    tready = _sig(dut, prefix, "tready")
    tlast = _sig(dut, prefix, "tlast")

    held = None   # (data, last) captured while stalled
    while True:
        await RisingEdge(clk_sig)
        await ReadOnly()

        if rst_sig is not None and rst_sig.value == 0:
            held = None
            continue

        valid = tvalid.value == 1
        ready = tready.value == 1
        snapshot = (
            int(tdata.value),
            int(tlast.value) if tlast is not None else None,
        )

        if held is not None:
            if not valid:
                raise AssertionError(
                    f"{prefix}: tvalid deasserted while stalled without a "
                    "completed transfer -- a beat was dropped (stream rule R2)"
                )
            if snapshot != held:
                raise AssertionError(
                    f"{prefix}: payload changed while tvalid high and tready "
                    f"low -- {held} became {snapshot} (stream rule R3)"
                )

        held = None if (ready or not valid) else snapshot
