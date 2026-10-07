"""Shared cocotb helpers for UTOSS devboard benches.

Deliberately small. This is not a verification framework -- it holds the few
things every bench in this repo would otherwise re-implement slightly
differently, which is how two benches end up disagreeing about what the stream
protocol means.

The runner puts this on PYTHONPATH automatically, so a bench just does:

    from utoss_tb import start_clock, reset_active_low, StreamSource, StreamSink
"""
from .clocking import start_clock, reset_active_low, width_of
from .params import assert_param, param, params, param_set_name
from .stream import StreamSource, StreamSink, check_stream_protocol

__all__ = [
    "start_clock",
    "reset_active_low",
    "width_of",
    "assert_param",
    "param",
    "params",
    "param_set_name",
    "StreamSource",
    "StreamSink",
    "check_stream_protocol",
]
