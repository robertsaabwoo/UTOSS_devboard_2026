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
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset(dut)

    dut.data_in.value = 0x3C
    dut.wr_en.value = 1
    await RisingEdge(dut.clk)
    latched_value = int(dut.data_out.value)

    dut.data_in.value = 0xFF  # change data_in mid-transaction
    for _ in range(3):
        await RisingEdge(dut.clk)
        if dut.busy.value == 1:
            assert int(dut.data_out.value) == latched_value, \
                "data_out changed while busy -- write handshake corrupted mid-transaction"

    dut.wr_en.value = 0
