"""cocotb testbench for rtl/fpga/reg_handshake.v.

Asserts the write-strobe handshake never corrupts data_out mid-transaction --
the kind of failure mode that would silently break a CPU/memory-facing
register interface.
"""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


async def reset(dut):
    dut.rst_n.value = 0
    dut.wr_en.value = 0
    dut.data_in.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_reset_state(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)
    assert dut.data_out.value == 0
    assert dut.busy.value == 0
    assert dut.ack.value == 0


@cocotb.test()
async def test_single_write_latches_and_acks(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)

    dut.data_in.value = 0xA5
    dut.wr_en.value = 1
    await RisingEdge(dut.clk)
    dut.wr_en.value = 0
    await RisingEdge(dut.clk)
    assert dut.data_out.value == 0xA5
    assert dut.busy.value == 1

    await RisingEdge(dut.clk)
    assert dut.ack.value == 1
    assert dut.busy.value == 0


@cocotb.test()
async def test_held_wr_en_does_not_corrupt_data(dut):
    """Holding wr_en high must not re-latch data_in into an in-flight write.

    Timing note: cocotb resumes from RisingEdge in the simulator's *active*
    region, before that edge's non-blocking assignments have settled -- so a
    signal read immediately after `await RisingEdge(clk)` still shows the
    value from the *previous* edge. Every check below is therefore read one
    edge after the edge that produced it.
    """
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)

    dut.data_in.value = 0x3C
    dut.wr_en.value = 1
    await RisingEdge(dut.clk)   # edge 1 latches 0x3C and raises busy

    dut.data_in.value = 0xFF    # change data mid-transaction, wr_en still held
    await RisingEdge(dut.clk)   # edge 2: a correct DUT ignores wr_en while busy
    assert dut.busy.value == 1, "busy should still be asserted from edge 1"
    assert int(dut.data_out.value) == 0x3C, "edge 1 did not latch data_in"

    await RisingEdge(dut.clk)   # edge 3 exposes what edge 2 actually did
    assert int(dut.data_out.value) == 0x3C, \
        "data_out re-latched while busy -- write handshake corrupted mid-transaction"

    dut.wr_en.value = 0
