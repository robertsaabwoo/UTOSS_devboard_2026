"""Clock and reset helpers."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


def width_of(signal) -> int:
    """Width in bits of a DUT signal.

    Benches in this repo are replayed across several parameter sets, so they
    must discover widths from the DUT rather than assume them. cocotb exposes
    this differently across versions, hence the fallbacks.
    """
    for attr in ("n_bits", "_range"):
        value = getattr(signal, attr, None)
        if isinstance(value, int):
            return value
    return len(signal.value)


def start_clock(dut, port: str = "clk", period_ns: float = 10.0):
    """Start a free-running clock on `dut.<port>` and return the handle.

    Period defaults to 10 ns (100 MHz), which is the `sys` domain target in
    rtl/ecp5_target.yaml. Pass the real period for other domains -- a bench
    that runs every domain at 100 MHz proves nothing about the CDC.
    """
    clock = Clock(getattr(dut, port), period_ns, units="ns")
    cocotb.start_soon(clock.start())
    return clock


async def reset_active_low(dut, clk: str = "clk", rst_n: str = "rst_n",
                           cycles: int = 3):
    """Assert an active-low reset for `cycles` edges, then release it.

    Matches the repo reset convention (see rtl/README.md): asynchronous assert,
    synchronous release, active low, one reset per clock domain.
    """
    clk_sig = getattr(dut, clk)
    rst_sig = getattr(dut, rst_n)
    rst_sig.value = 0
    for _ in range(cycles):
        await RisingEdge(clk_sig)
    rst_sig.value = 1
    await RisingEdge(clk_sig)
