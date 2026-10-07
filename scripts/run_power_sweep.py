#!/usr/bin/env python3
"""Render + run the power submodule's SPICE sweep(s) declared in
io_specs/power.yaml, and check every asserted net's min_v/max_v against
spec at every swept operating point.

Sweep axes are pure data (io_specs/power.yaml `sweeps:`) rendered into a
.cir.tmpl testbench via {{axis_id}} placeholders -- adding a new axis, or a
new sweep entirely, is a YAML + template edit, not a change to this script.
A single-point "sweep" (start == stop, or a one-element `values:` list) is
just the degenerate case of the same code path.
"""
import itertools
import re
import subprocess
import sys
import pathlib
import tempfile
from typing import Optional

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "io_specs" / "power.yaml"

NUMBER_RE = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def axis_values(axis: dict) -> list:
    """Values for one axis: an explicit `values:` list, or a start/stop/step ramp.

    The ramp includes `start`, and includes `stop` only when `step` divides the
    span evenly -- otherwise it stops at the last whole step before `stop`
    (e.g. 1.667..10.0 by 2.0 ends at 9.667).
    """
    if "values" in axis:
        return [float(v) for v in axis["values"]]

    start, stop, step = axis["start"], axis["stop"], axis["step"]
    if step == 0:
        raise ValueError(f"axis '{axis['id']}': step must be non-zero")
    if (stop - start) / step < 0:
        raise ValueError(
            f"axis '{axis['id']}': step {step} moves away from stop "
            f"(start={start}, stop={stop})"
        )
    n_steps = int((stop - start) / step + 1e-9)
    return [round(start + i * step, 10) for i in range(n_steps + 1)]


def validate_template(template_text: str, axis_ids: list, sweep_name: str) -> list:
    """Placeholders in the template and declared axis ids must correspond 1:1.

    Catches both directions of a config typo: a {{placeholder}} with no axis
    behind it (would render a literal brace into the netlist), and an axis
    that is declared -- and so multiplies the point count -- but never
    substituted anywhere, i.e. a silent no-op sweep dimension.
    """
    placeholders = set(PLACEHOLDER_RE.findall(template_text))
    declared = set(axis_ids)
    failures = []
    for missing in sorted(placeholders - declared):
        failures.append(
            f"sweep '{sweep_name}': template references {{{{{missing}}}}} but no axis declares id '{missing}'"
        )
    for unused in sorted(declared - placeholders):
        failures.append(
            f"sweep '{sweep_name}': axis '{unused}' is declared but never referenced "
            f"as {{{{{unused}}}}} in the template — it would silently multiply run time without varying anything"
        )
    return failures


def render(template_text: str, point: dict) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in point:
            raise KeyError(f"template references undeclared axis '{{{{{key}}}}}'")
        return str(point[key])

    return PLACEHOLDER_RE.sub(sub, template_text)


def run_ngspice(cir_path: pathlib.Path) -> tuple[int, str]:
    result = subprocess.run(
        ["ngspice", "-b", cir_path.name],
        cwd=cir_path.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout + "\n" + result.stderr


def parse_voltage(output: str, node: str) -> Optional[float]:
    """Find the last line mentioning `node` and pull the last number off it.

    Robust to ngspice print-format variation (e.g. "plus5v = 4.98e+00" vs
    "v(plus5v) = 4.98e+00" vs different column spacing) since we don't
    anchor on an exact prefix/operator, just: line mentions the node,
    take its last numeric token.
    """
    best = None
    for line in output.splitlines():
        if node.lower() in line.lower():
            matches = re.findall(NUMBER_RE, line)
            if matches:
                best = float(matches[-1])
    return best


def run_sweep(sweep: dict, nets_by_name: dict) -> list:
    failures = []
    template_path = ROOT / sweep["testbench_template"]
    template_text = template_path.read_text()

    axes = sweep["axes"]
    axis_ids = [a["id"] for a in axes]

    # Fail the whole sweep up front on a bad config rather than emitting the
    # same render error once per point.
    config_failures = validate_template(template_text, axis_ids, sweep["name"])
    if config_failures:
        return config_failures

    try:
        value_lists = [axis_values(a) for a in axes]
    except ValueError as exc:
        return [f"sweep '{sweep['name']}': {exc}"]

    n_points = 1
    for vl in value_lists:
        n_points *= len(vl)
    print(f"--- sweep '{sweep['name']}': {n_points} point(s) across axes {axis_ids} ---")

    for combo in itertools.product(*value_lists):
        point = dict(zip(axis_ids, combo))
        point_desc = ", ".join(f"{k}={v}" for k, v in point.items())
        rendered = render(template_text, point)

        with tempfile.NamedTemporaryFile(
            "w", dir=template_path.parent, prefix="tmp", suffix=".cir", delete=False
        ) as tmp:
            tmp.write(rendered)
            tmp_path = pathlib.Path(tmp.name)
        try:
            returncode, output = run_ngspice(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        if returncode != 0:
            failures.append(f"[{point_desc}] ngspice exited {returncode}: simulation did not complete")
            continue

        for assertion in sweep["assert_nets"]:
            node, net_name = assertion["node"], assertion["net"]
            voltage = parse_voltage(output, node)
            if voltage is None:
                failures.append(f"[{point_desc}] {net_name}: could not find node '{node}' in ngspice output")
                continue

            net_spec = nets_by_name.get(net_name)
            if net_spec is None:
                failures.append(f"[{point_desc}] {net_name}: no matching entry in io_specs/power.yaml")
                continue

            min_v, max_v = net_spec.get("min_v"), net_spec.get("max_v")
            if min_v is not None and voltage < min_v:
                failures.append(f"[{point_desc}] {net_name}: simulated {voltage:.4f}V is below spec min {min_v}V")
            if max_v is not None and voltage > max_v:
                failures.append(f"[{point_desc}] {net_name}: simulated {voltage:.4f}V is above spec max {max_v}V")

    return failures


def main() -> None:
    spec = yaml.safe_load(SPEC_PATH.read_text())
    nets_by_name = {n["name"]: n for n in spec["nets"]}
    sweeps = spec.get("sweeps", [])

    if not sweeps:
        print("No sweeps declared in io_specs/power.yaml — nothing to verify.")
        sys.exit(1)

    all_failures = []
    for sweep in sweeps:
        all_failures.extend(run_sweep(sweep, nets_by_name))

    if all_failures:
        print("\nSPICE SWEEP VERIFY FAILED:")
        for f in all_failures:
            print(f"  - {f}")
        sys.exit(1)

    print("\nSPICE SWEEP VERIFY PASSED")


if __name__ == "__main__":
    main()
