"""Bench for rtl/examples/fifo.v. Checks the spec in the module header.

Inputs are driven on the falling edge and outputs read on the next falling
edge, so every check sees the state after exactly one rising edge.
"""
import cocotb
from cocotb.triggers import FallingEdge, RisingEdge

from utoss_tb import assert_param, param, start_clock, width_of


async def setup(dut):
    """Start the clock, reset, and return (width, depth)."""
    start_clock(dut)
    dut.rst_n.value = 0
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    dut.wr_data.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)

    width = width_of(dut.wr_data)
    depth = param("DEPTH") or 16
    assert_param("WIDTH", width)
    return width, depth


async def cycle(dut, wr=False, data=0, rd=False):
    """Apply one cycle of inputs, then return to idle."""
    dut.wr_en.value = int(wr)
    dut.wr_data.value = data
    dut.rd_en.value = int(rd)
    await FallingEdge(dut.clk)
    dut.wr_en.value = 0
    dut.rd_en.value = 0


def values(count, width):
    """Distinct-as-possible test values that fit in `width` bits."""
    mask = (1 << width) - 1
    return [(0x9E3779B1 * (i + 1)) & mask for i in range(count)]


@cocotb.test()
async def test_reset_state(dut):
    """Out of reset the FIFO is empty and not full."""
    await setup(dut)
    assert dut.empty.value == 1, "empty is not set after reset"
    assert dut.full.value == 0, "full is set after reset"


@cocotb.test()
async def test_rd_data_valid_before_rd_en(dut):
    """After one write, rd_data shows it without any read being requested."""
    width, _ = await setup(dut)
    value = values(1, width)[0]
    await cycle(dut, wr=True, data=value)
    assert dut.empty.value == 0, "still empty after a write"
    got = int(dut.rd_data.value)
    assert got == value, (
        "after one write and no read, rd_data is 0x%x, expected 0x%x. rd_data "
        "must show the oldest entry as soon as empty=0, before rd_en (see the "
        "spec in fifo.v). A registered read output that updates on rd_en is "
        "one entry behind, and makes most other tests fail too." % (got, value))


@cocotb.test()
async def test_fill_then_drain_in_order(dut):
    """DEPTH writes make it full; reads return them oldest first."""
    width, depth = await setup(dut)
    data = values(depth, width)

    for i, value in enumerate(data):
        assert dut.full.value == 0, "full after only %d of %d writes" % (i, depth)
        await cycle(dut, wr=True, data=value)
        assert dut.empty.value == 0, "still empty after a write"
    assert dut.full.value == 1, "not full after %d writes" % depth

    for i, expected in enumerate(data):
        assert dut.empty.value == 0, "empty after only %d of %d reads" % (i, depth)
        got = int(dut.rd_data.value)
        assert got == expected, (
            "read %d returned 0x%x, expected 0x%x: entries out of order or "
            "corrupted" % (i, got, expected))
        await cycle(dut, rd=True)
    assert dut.empty.value == 1, "not empty after reading everything back"
    assert dut.full.value == 0, "still full after reading everything back"


@cocotb.test()
async def test_write_while_full_is_ignored(dut):
    """A write while full must not overwrite anything already stored."""
    width, depth = await setup(dut)
    data = values(depth + 1, width)

    for value in data[:depth]:
        await cycle(dut, wr=True, data=value)
    await cycle(dut, wr=True, data=data[depth])   # one too many

    for i, expected in enumerate(data[:depth]):
        got = int(dut.rd_data.value)
        assert got == expected, (
            "read %d returned 0x%x, expected 0x%x: the write while full "
            "overwrote stored data" % (i, got, expected))
        await cycle(dut, rd=True)
    assert dut.empty.value == 1, (
        "data left over after draining: the write while full was stored")


@cocotb.test()
async def test_read_while_empty_is_ignored(dut):
    """A read while empty changes nothing; the next write reads back intact."""
    width, _ = await setup(dut)
    await cycle(dut, rd=True)
    assert dut.empty.value == 1, "read while empty left the FIFO non-empty"

    value = values(1, width)[0]
    await cycle(dut, wr=True, data=value)
    got = int(dut.rd_data.value)
    assert got == value, (
        "after a read while empty, a write read back as 0x%x not 0x%x: the "
        "read pointer moved" % (got, value))


@cocotb.test()
async def test_simultaneous_read_and_write(dut):
    """Read and write in one cycle: the level stays put, order is kept."""
    width, depth = await setup(dut)
    data = values(depth + 4, width)

    await cycle(dut, wr=True, data=data[0])
    for i in range(1, len(data)):
        got = int(dut.rd_data.value)
        assert got == data[i - 1], (
            "cycle %d read 0x%x, expected 0x%x during simultaneous read and "
            "write" % (i, got, data[i - 1]))
        await cycle(dut, wr=True, data=data[i], rd=True)
        assert dut.empty.value == 0, (
            "went empty while reading and writing together: the read and "
            "write were not both counted")
        assert dut.full.value == 0, "went full holding a single entry"
