"""cocotb bench for rtl/examples/example_fifo.v -- the worked example.

Read this before writing your own bench. It is built around four ideas, and
they are the four things rtl_tests/README.md asks of every bench here:

1.  **Stay parameter-generic.** The runner replays this file at WIDTH 1/3/8/32
    and DEPTH 2/7/16/64, so nothing may hard-code a width, a depth, or a test
    vector that only fits one of them. Everything below derives from
    `width_of(dut.rd_data)` and `dut.DEPTH`.

2.  **Compare against a reference model, not against hand-written expected
    values.** `collections.deque` is the model. A hand-written expectation can
    only cover the cases you already thought of, and the bugs are in the ones
    you did not.

3.  **Go at the boundaries deliberately.** `test_concurrent_rw_at_every_level`
    walks a simultaneous read+write through every occupancy from 0 to DEPTH.
    A random test will wander near those points but will not reliably hit
    "write and read on the same edge while exactly full", which is where FIFO
    off-by-ones actually live.

4.  **Say what a failure means.** Every assertion message states the
    consequence for the design, not just the mismatch. The runner now scrapes
    these out of the simulator log into the summary table, so this text is
    what a teammate sees when they break the build six weeks from now.
"""
import collections
import random

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly

from utoss_tb import assert_param, reset_active_low, start_clock, width_of


def geometry(dut):
    """Width and depth this run was actually elaborated with."""
    width = width_of(dut.rd_data)
    depth = int(dut.DEPTH.value)
    return width, depth


async def setup(dut):
    """Start the clock, reset, and check the harness really applied the params."""
    start_clock(dut)
    await reset_active_low(dut)
    width, depth = geometry(dut)
    # Proves the harness rather than the DUT: if bench.yaml asked for WIDTH=32
    # and the DUT came up 8 bits wide, the override never reached the simulator
    # and this parameter set is testing nothing.
    assert_param("WIDTH", width)
    assert_param("DEPTH", depth)
    return width, depth


async def push(dut, value):
    """Drive one write. Returns True if the FIFO accepted it."""
    await ReadOnly()
    accepted = dut.full.value == 0
    await RisingEdge(dut.clk)
    dut.wr_data.value = value
    dut.wr_en.value = 1
    await RisingEdge(dut.clk)
    dut.wr_en.value = 0
    return accepted


async def pop(dut):
    """Pop one entry. Returns the value read, or None if it was empty."""
    await ReadOnly()
    if dut.empty.value == 1:
        return None
    value = int(dut.rd_data.value)
    await RisingEdge(dut.clk)
    dut.rd_en.value = 1
    await RisingEdge(dut.clk)
    dut.rd_en.value = 0
    return value


@cocotb.test()
async def test_reset_state(dut):
    """Out of reset the FIFO must be empty, not full, and report level 0.

    Worth keeping even once better tests exist: the payload is power-gated, so
    every imaging pass starts from a cold reset. A FIFO that comes up claiming
    to hold data would have the compressor read garbage on the first pass.
    """
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    await setup(dut)

    assert dut.empty.value == 1, "FIFO is not empty after reset"
    assert dut.full.value == 0, "FIFO claims to be full after reset"
    assert int(dut.level.value) == 0, (
        "level is non-zero after reset -- a consumer would read entries that "
        "were never written"
    )


@cocotb.test()
async def test_fill_drain_fifo_order(dut):
    """Fill to exactly DEPTH, then drain. Order must be first-in-first-out."""
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    width, depth = await setup(dut)
    mask = (1 << width) - 1

    written = [(i * 7 + 1) & mask for i in range(depth)]
    for index, value in enumerate(written):
        assert await push(dut, value), (
            "FIFO reported full after only %d of %d writes" % (index, depth)
        )

    await ReadOnly()
    assert dut.full.value == 1, "FIFO is not full after DEPTH writes"
    assert int(dut.level.value) == depth, (
        "level reads %d after DEPTH writes, expected %d"
        % (int(dut.level.value), depth)
    )
    await RisingEdge(dut.clk)

    for index, expected in enumerate(written):
        got = await pop(dut)
        assert got == expected, (
            "entry %d came back as 0x%x, expected 0x%x -- FIFO is not "
            "preserving order, so a pixel stream through it would be scrambled"
            % (index, got if got is not None else -1, expected)
        )

    await ReadOnly()
    assert dut.empty.value == 1, "FIFO is not empty after draining every entry"


@cocotb.test()
async def test_write_while_full_is_dropped_not_destructive(dut):
    """A write while full must be ignored, leaving queued entries untouched.

    This is the assertion that matters most. A FIFO that overwrites its oldest
    entry under pressure loses data with no symptom at all -- the capture looks
    successful and the cube is wrong. Dropping the new write is recoverable
    (the real fifo_sync counts it, per I-01); corrupting a queued entry is not.
    """
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    width, depth = await setup(dut)
    mask = (1 << width) - 1

    written = [(i * 3 + 2) & mask for i in range(depth)]
    for value in written:
        await push(dut, value)

    # Hammer a distinctive value in while full.
    intruder = (~written[0]) & mask
    for _ in range(3):
        accepted = await push(dut, intruder)
        assert not accepted, "FIFO accepted a write while reporting full"

    await ReadOnly()
    assert int(dut.level.value) == depth, (
        "level changed while writes were being refused -- it now reads %d, "
        "expected %d" % (int(dut.level.value), depth)
    )
    await RisingEdge(dut.clk)

    for index, expected in enumerate(written):
        got = await pop(dut)
        assert got == expected, (
            "entry %d is 0x%x, expected 0x%x -- a write while full corrupted "
            "data that was already queued" % (index, got, expected)
        )


@cocotb.test()
async def test_read_while_empty_is_harmless(dut):
    """Reading an empty FIFO must not corrupt state or fake an entry."""
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    width, _ = await setup(dut)
    mask = (1 << width) - 1

    for _ in range(3):
        got = await pop(dut)
        assert got is None, "FIFO returned data while reporting empty"

    await ReadOnly()
    assert int(dut.level.value) == 0, (
        "level is %d after reading an empty FIFO -- the pointers have gone out "
        "of step and every subsequent read is wrong" % int(dut.level.value)
    )
    await RisingEdge(dut.clk)

    # It must still work normally afterwards.
    value = 0xA5 & mask
    assert await push(dut, value)
    got = await pop(dut)
    assert got == value, (
        "FIFO is broken after an underflow: wrote 0x%x, read 0x%x" % (value, got)
    )


@cocotb.test()
async def test_concurrent_rw_at_every_level(dut):
    """Simultaneous read and write at every occupancy from 0 to DEPTH.

    The level must not change, and the value read must be the oldest entry.
    This is the off-by-one arm in the count logic, and it is wrong only at the
    extremes -- so it is walked exhaustively rather than sampled.
    """
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    width, depth = await setup(dut)
    mask = (1 << width) - 1

    for occupancy in range(depth + 1):
        await reset_active_low(dut)
        model = collections.deque()

        for i in range(occupancy):
            value = (i + 1) & mask
            await push(dut, value)
            model.append(value)

        await ReadOnly()
        before = int(dut.level.value)
        was_empty = dut.empty.value == 1
        was_full = dut.full.value == 1
        head = int(dut.rd_data.value) if not was_empty else None
        await RisingEdge(dut.clk)

        assert before == occupancy, (
            "level reads %d after %d writes" % (before, occupancy)
        )

        # Assert read and write on the same edge.
        dut.wr_data.value = (0xC3 ^ occupancy) & mask
        dut.wr_en.value = 1
        dut.rd_en.value = 1
        await RisingEdge(dut.clk)
        dut.wr_en.value = 0
        dut.rd_en.value = 0
        await RisingEdge(dut.clk)

        await ReadOnly()
        after = int(dut.level.value)
        await RisingEdge(dut.clk)

        if was_empty:
            # Nothing to read, so only the write lands.
            assert after == 1, (
                "concurrent read+write on an empty FIFO gave level %d, "
                "expected 1 -- the read of an empty FIFO was counted" % after
            )
        elif was_full:
            # Nothing can be written, so only the read lands.
            assert after == depth - 1, (
                "concurrent read+write on a full FIFO gave level %d, expected "
                "%d -- the refused write was counted" % (after, depth - 1)
            )
            assert head == model[0], (
                "full FIFO presented 0x%x as its oldest entry, expected 0x%x"
                % (head, model[0])
            )
        else:
            assert after == occupancy, (
                "concurrent read+write at occupancy %d changed level to %d -- "
                "the simultaneous case is miscounted, which will drift the "
                "FIFO's idea of its own fullness over a long capture"
                % (occupancy, after)
            )
            assert head == model[0], (
                "at occupancy %d the oldest entry read as 0x%x, expected 0x%x"
                % (occupancy, head, model[0])
            )


@cocotb.test()
async def test_random_traffic_against_reference_model(dut):
    """Randomized read/write traffic compared beat for beat with a deque.

    Seeded, so a failure is reproducible. This is the test that catches what
    the targeted tests above did not think of.
    """
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    width, depth = await setup(dut)
    mask = (1 << width) - 1

    rng = random.Random(0xC0FFEE ^ (width << 8) ^ depth)
    model = collections.deque()
    operations = 2000

    for step in range(operations):
        do_write = rng.random() < 0.55
        do_read = rng.random() < 0.45

        await ReadOnly()
        is_full = dut.full.value == 1
        is_empty = dut.empty.value == 1
        level = int(dut.level.value)
        head = int(dut.rd_data.value) if not is_empty else None

        assert level == len(model), (
            "step %d: level reads %d, model says %d -- the FIFO has lost track "
            "of its own occupancy" % (step, level, len(model))
        )
        assert is_full == (len(model) == depth), (
            "step %d: full=%d at occupancy %d of %d -- a wrong full flag either "
            "stalls the producer forever or invites an overflow"
            % (step, int(is_full), len(model), depth)
        )
        assert is_empty == (len(model) == 0), (
            "step %d: empty=%d at occupancy %d -- a wrong empty flag makes the "
            "consumer read entries that do not exist"
            % (step, int(is_empty), len(model))
        )
        if head is not None:
            assert head == model[0], (
                "step %d: oldest entry reads 0x%x, model says 0x%x"
                % (step, head, model[0])
            )

        value = rng.randrange(0, mask + 1)
        await RisingEdge(dut.clk)
        dut.wr_data.value = value
        dut.wr_en.value = 1 if do_write else 0
        dut.rd_en.value = 1 if do_read else 0
        await RisingEdge(dut.clk)
        dut.wr_en.value = 0
        dut.rd_en.value = 0

        # Mirror exactly what the DUT was able to do on that edge.
        if do_read and not is_empty:
            model.popleft()
        if do_write and not is_full:
            model.append(value)

    # Drain and confirm the contents match, in order.
    await RisingEdge(dut.clk)
    while model:
        expected = model.popleft()
        got = await pop(dut)
        assert got == expected, (
            "drain mismatch: read 0x%x, expected 0x%x" % (got, expected)
        )

    await ReadOnly()
    assert dut.empty.value == 1, "FIFO is not empty after draining the model"


@cocotb.test()
async def test_reset_mid_traffic_empties_the_fifo(dut):
    """Reset while entries are queued must return the FIFO to empty.

    Every imaging pass is a cold start on this payload, so a FIFO that keeps
    stale entries across reset would feed the previous pass's samples into the
    beginning of the next cube.
    """
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    width, depth = await setup(dut)
    mask = (1 << width) - 1

    for i in range(depth):
        await push(dut, (i + 5) & mask)

    await reset_active_low(dut)
    await ReadOnly()
    assert dut.empty.value == 1, "FIFO still reports data after reset"
    assert int(dut.level.value) == 0, (
        "level is %d after reset -- stale entries from the previous capture "
        "would be read as part of the next one" % int(dut.level.value)
    )
    await RisingEdge(dut.clk)

    fresh = 0x5A & mask
    assert await push(dut, fresh)
    got = await pop(dut)
    assert got == fresh, (
        "after reset the FIFO returned 0x%x instead of the freshly written "
        "0x%x -- the read pointer did not reset with the write pointer"
        % (got, fresh)
    )
