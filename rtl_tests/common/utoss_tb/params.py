"""Read back the parameter set the runner elaborated this run with.

Why this exists: the runner applies a bench.yaml parameter set on the
simulator command line (`-PWIDTH=64`). If that flag is ever dropped -- a
renamed parameter, a renamed toplevel, a simulator that quietly ignores an
unknown `-P` target -- every parameter set elaborates at the module's default
width instead, all three runs pass, and the width sweep silently proves
nothing. That is the exact class of failure this whole harness is built to
refuse.

So the runner also exports the parameter set into the environment, and
`assert_param` compares what was requested against what the DUT actually
elaborated to. Call it once at the top of a bench for each width parameter:

    from utoss_tb import assert_param, width_of
    assert_param("WIDTH", width_of(dut.data_out))
"""
import os
from typing import Dict, Optional


def param_set_name() -> str:
    """Name of the bench.yaml parameter set being run ("" outside the runner)."""
    return os.environ.get("UTOSS_PARAM_SET", "")


def params() -> Dict[str, int]:
    """Every parameter the runner overrode, as ints."""
    found = {}
    for key, value in os.environ.items():
        if key.startswith("UTOSS_PARAM_") and key != "UTOSS_PARAM_SET":
            try:
                found[key[len("UTOSS_PARAM_"):]] = int(value)
            except ValueError:
                continue
    return found


def param(name: str) -> Optional[int]:
    """The requested value of one parameter, or None if it was not overridden.

    None is the normal answer when a bench is run by hand outside the runner,
    so callers must treat it as "nothing to check" rather than as a failure.
    """
    return params().get(name)


def assert_param(name: str, actual: int) -> None:
    """Fail if the DUT did not elaborate to the requested parameter value.

    A no-op when the parameter was not overridden (running the bench by hand),
    so it is safe to leave in unconditionally.
    """
    requested = param(name)
    if requested is None:
        return
    if int(actual) != requested:
        raise AssertionError(
            "parameter %s: bench.yaml asked for %d but the DUT elaborated to "
            "%d. The parameter override did not reach the simulator, so this "
            "parameter set is not testing what it claims to. Check that the "
            "module really declares a parameter named %s and that "
            "bench.yaml's `toplevel` matches the module name."
            % (name, requested, actual, name)
        )
