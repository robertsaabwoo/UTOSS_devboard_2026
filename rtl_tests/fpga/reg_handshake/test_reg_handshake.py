"""Reference cocotb bench -- rtl/fpga/reg_handshake.v.

This is the worked example for every bench in this repo. Three things in it are
the pattern to copy:

1.  It is **width-generic**. The runner replays it at WIDTH=1, 8 and 64 (see
    bench.yaml), so nothing may hard-code a width or a literal that only fits
    one of them. `width_of(dut.data_out)` and `mask` below are how.
2.  It asserts the thing that would actually hurt, not the thing that is easy
    to assert: that an in-flight write cannot be corrupted. A bench that only
    checks the happy path passes on a broken DUT.
3.  Every check says, in its assertion message, what a failure means for the
    design -- not just which number mismatched.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from utoss_tb import assert_param, start_clock, width_of


async def reset(dut):
    """Hold reset for a few edges, then release it synchronously."""
    dut.rst_n.value = 0
    dut.wr_en.value = 0
    dut.data_in.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


def patterns(width):
    """Test values that exercise the full bus at any width.

    all-ones and all-zeroes catch a stuck bit; the alternating pattern catches
    a width mis-slice or a swapped bit order, which an all-ones vector cannot.
    """
    mask = (1 << width) - 1
    return [mask, 0, 0xA5A5A5A5A5A5A5A5 & mask, 0x5A5A5A5A5A5A5A5A & mask]


@cocotb.test()
async def test_reset_state(dut):
    """Reset must land the register in a defined, idle state.

    A register block that comes out of reset with busy or ack asserted hangs
    the supervisor's first transaction after every power-gated wake-up.
    """
    start_clock(dut)
    await reset(dut)
    # Proves the harness, not the DUT: if bench.yaml asked for WIDTH=64 and the
    # DUT came up 8 bits wide, the parameter override never reached the
    # simulator and this parameter set is testing nothing.
    assert_param("WIDTH", width_of(dut.data_out))
    assert dut.data_out.value == 0, "data_out not cleared by reset"
    assert dut.busy.value == 0, "busy asserted out of reset -- bus would hang"
    assert dut.ack.value == 0, "ack asserted out of reset -- phantom completion"


@cocotb.test()
async def test_single_write_latches_and_acks(dut):
    """One write per pattern: data lands, busy rises, ack pulses exactly once."""
    start_clock(dut)
    await reset(dut)
    width = width_of(dut.data_out)

    for value in patterns(width):
        dut.data_in.value = value
        dut.wr_en.value = 1
        await RisingEdge(dut.clk)
        dut.wr_en.value = 0
        await RisingEdge(dut.clk)
        assert int(dut.data_out.value) == value, (
            f"write of 0x{value:x} did not land (got 0x{int(dut.data_out.value):x})"
        )
        assert dut.busy.value == 1, "busy did not rise with the accepted write"

        await RisingEdge(dut.clk)
        assert dut.ack.value == 1, "no ack for an accepted write -- master would time out"
        assert dut.busy.value == 0, "busy did not clear after ack"

        await RisingEdge(dut.clk)
        assert dut.ack.value == 0, (
            "ack is not a single-cycle pulse -- a master counting acks would "
            "double-count every write"
        )


@cocotb.test()
async def test_held_wr_en_does_not_corrupt_data(dut):
    """Holding wr_en high must not re-latch data_in into an in-flight write.

    Timing note worth internalising before you write your own bench: cocotb
    resumes from RisingEdge in the simulator's *active* region, before that
    edge's non-blocking assignments have settled -- so a signal read
    immediately after `await RisingEdge(clk)` still shows the value from the
    *previous* edge. Every check below is therefore read one edge after the
    edge that produced it. Getting this wrong is the single most common reason
    a bench "passes" against a broken DUT.
    """
    start_clock(dut)
    await reset(dut)
    width = width_of(dut.data_out)
    mask = (1 << width) - 1

    first = 0x3C & mask
    second = 0xFF & mask
    if first == second:
        # At WIDTH=1 both patterns collapse to the same value and the test
        # would assert nothing. Pick two values that still differ.
        first, second = 0, 1

    dut.data_in.value = first
    dut.wr_en.value = 1
    await RisingEdge(dut.clk)   # edge 1 latches `first` and raises busy

    dut.data_in.value = second  # change data mid-transaction, wr_en still held
    await RisingEdge(dut.clk)   # edge 2: a correct DUT ignores wr_en while busy
    assert dut.busy.value == 1, "busy should still be asserted from edge 1"
    assert int(dut.data_out.value) == first, "edge 1 did not latch data_in"

    await RisingEdge(dut.clk)   # edge 3 exposes what edge 2 actually did
    assert int(dut.data_out.value) == first, (
        "data_out re-latched while busy -- write handshake corrupted "
        "mid-transaction"
    )

    dut.wr_en.value = 0
