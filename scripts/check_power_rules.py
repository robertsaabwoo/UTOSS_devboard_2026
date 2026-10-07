#!/usr/bin/env python3
"""Energy and bring-up gate for io_specs/power.yaml.

Three independent checks, all collected before exiting so one run reports
everything that is wrong:

  budget    -- walk each state's loads up their converter chains, apply
               efficiency and quiescent current, assert the total draw at the
               input rail stays under the state's declared ceiling.
  ramp      -- assert every rail's soft-start slew lands inside the FPGA's
               datasheet tRAMP window.
  sequence  -- assert declared bring-up orderings actually hold, with margin,
               given each rail's enable delay and soft-start time.

This is deliberately NOT the SPICE check. scripts/run_power_sweep.py verifies
regulation (does a rail stay inside min_v/max_v under load and line
variation). This script verifies energy and timing, which an operating-point
simulation cannot see.
"""
import argparse
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POWER_SPEC = ROOT / "io_specs" / "power.yaml"


def load_spec(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


def nets_by_name(spec: dict) -> dict:
    return {net["name"]: net for net in spec.get("nets", [])}


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------

def input_power_mw(nets: dict, rail_name: str, load_ma: float, input_rail: str) -> tuple:
    """Referred `load_ma` drawn from `rail_name` back to `input_rail`.

    Returns (power_mw_at_input, failures). Walks converted_from links,
    dividing by each stage's efficiency. Quiescent current is NOT added here
    -- it is per-converter, not per-load, so adding it inside this walk would
    double-count it once per load on a shared rail.
    """
    failures = []
    net = nets.get(rail_name)
    if net is None:
        return 0.0, [f"load references unknown rail '{rail_name}'"]

    nominal = net.get("nominal_v")
    if nominal is None:
        return 0.0, [f"rail '{rail_name}' has no nominal_v — cannot compute power"]

    power_mw = nominal * load_ma
    seen = [rail_name]

    while net["name"] != input_rail:
        parent_name = net.get("converted_from")
        if parent_name is None:
            failures.append(
                f"rail '{net['name']}' has no `converted_from` and is not the input rail "
                f"'{input_rail}' — the conversion chain does not reach the input"
            )
            return power_mw, failures
        if parent_name in seen:
            failures.append(f"conversion chain loops: {' -> '.join(seen)} -> {parent_name}")
            return power_mw, failures

        converter = net.get("converter") or {}
        eff = converter.get("efficiency_pct")
        if eff is None:
            failures.append(f"rail '{net['name']}' has no converter.efficiency_pct")
            return power_mw, failures
        if not 0 < eff <= 100:
            failures.append(f"rail '{net['name']}' efficiency_pct {eff} is not in (0, 100]")
            return power_mw, failures

        power_mw /= eff / 100.0
        seen.append(parent_name)
        net = nets.get(parent_name)
        if net is None:
            failures.append(f"rail '{seen[-2]}' converted_from unknown rail '{parent_name}'")
            return power_mw, failures

    return power_mw, failures


def check_budget(spec: dict) -> list:
    failures = []
    budget = spec.get("power_budget")
    if budget is None:
        return ["power.yaml has no `power_budget` block — nothing gates energy use"]

    nets = nets_by_name(spec)
    input_rail = budget.get("input_rail")
    if input_rail not in nets:
        return [f"power_budget.input_rail '{input_rail}' is not a declared net"]

    states = budget.get("states") or []
    if not states:
        return ["power_budget declares no states"]

    for state in states:
        name = state.get("name", "<unnamed>")
        ceiling = state.get("max_input_power_mw")
        if ceiling is None:
            failures.append(f"state '{name}': no max_input_power_mw — the state is unbounded")
            continue

        rails_off = set(state.get("rails_off") or [])
        for off_rail in rails_off:
            if off_rail not in nets:
                failures.append(f"state '{name}': rails_off lists unknown rail '{off_rail}'")

        total_mw = 0.0
        active_rails = set()

        for load in state.get("loads") or []:
            rail = load.get("rail")
            consumer = load.get("consumer", "<unnamed load>")
            if rail in rails_off:
                failures.append(
                    f"state '{name}': '{consumer}' draws from '{rail}', which the same state "
                    f"lists as off — the budget and the power tree disagree"
                )
                continue

            current_ma = (load.get("static_ma") or 0) + (load.get("dynamic_allowance_ma") or 0)
            if current_ma == 0:
                continue
            mw, load_failures = input_power_mw(nets, rail, current_ma, input_rail)
            failures.extend(f"state '{name}': {f}" for f in load_failures)
            total_mw += mw
            active_rails.add(rail)

        # Converter quiescent current, counted once per powered converter
        # regardless of how many loads hang off it.
        for rail_name, net in nets.items():
            if rail_name in rails_off or rail_name == input_rail:
                continue
            converter = net.get("converter") or {}
            iq = converter.get("quiescent_ma") or 0
            if iq == 0:
                continue
            parent = net.get("converted_from")
            if parent is None:
                continue
            mw, q_failures = input_power_mw(nets, parent, iq, input_rail)
            failures.extend(f"state '{name}': quiescent of '{rail_name}': {f}" for f in q_failures)
            total_mw += mw

        if total_mw > ceiling:
            failures.append(
                f"state '{name}': draws {total_mw:.1f} mW at {input_rail}, over the "
                f"{ceiling} mW ceiling by {total_mw - ceiling:.1f} mW"
            )
        else:
            print(f"  budget: state '{name}' draws {total_mw:.1f} mW of {ceiling} mW allowed "
                  f"({100.0 * total_mw / ceiling:.0f}%)")

    return failures


# --------------------------------------------------------------------------
# Ramp rate
# --------------------------------------------------------------------------

def check_ramp(spec: dict) -> list:
    failures = []
    rules = spec.get("rail_rules") or {}
    window = rules.get("ramp_rate_v_per_ms")
    if window is None:
        return ["power.yaml rail_rules has no ramp_rate_v_per_ms window"]

    global_min, global_max = window.get("min"), window.get("max")
    if global_min is None or global_max is None:
        return ["rail_rules.ramp_rate_v_per_ms needs both min and max"]

    per_rail_max = rules.get("per_rail_ramp_max_v_per_ms") or {}

    for net in spec.get("nets", []):
        if net.get("type") != "rail":
            continue
        name = net["name"]
        soft_start = net.get("soft_start_ms")
        nominal = net.get("nominal_v")
        if soft_start is None:
            failures.append(f"rail '{name}': no soft_start_ms — ramp rate cannot be verified")
            continue
        if soft_start <= 0:
            failures.append(f"rail '{name}': soft_start_ms must be positive, got {soft_start}")
            continue

        rate = nominal / soft_start
        # The tighter of the global window and any per-rail ceiling wins, so
        # a per-rail entry can only ever make the check stricter.
        ceiling = min(global_max, per_rail_max.get(name, global_max))

        if rate < global_min:
            failures.append(
                f"rail '{name}': ramps at {rate:.4f} V/ms, below the {global_min} V/ms minimum "
                f"(soft_start_ms {soft_start} is too slow for {nominal}V)"
            )
        if rate > ceiling:
            limit_source = "per-rail limit" if ceiling < global_max else "datasheet maximum"
            failures.append(
                f"rail '{name}': ramps at {rate:.4f} V/ms, above the {ceiling} V/ms {limit_source} "
                f"(soft_start_ms {soft_start} is too fast for {nominal}V)"
            )

    return failures


# --------------------------------------------------------------------------
# Bring-up sequencing
# --------------------------------------------------------------------------

def time_to_reach(net: dict, threshold_v: float) -> tuple:
    """When a rail crosses `threshold_v`, assuming a linear monotonic ramp.

    Linear is an approximation -- real soft-start curves are not straight
    lines. It is the conservative direction for these checks only because we
    apply a margin on top; the margin is what absorbs the curve shape.
    """
    nominal = net.get("nominal_v")
    soft_start = net.get("soft_start_ms")
    delay = net.get("enable_delay_ms")
    name = net["name"]

    for label, value in (("nominal_v", nominal), ("soft_start_ms", soft_start),
                         ("enable_delay_ms", delay)):
        if value is None:
            return None, f"rail '{name}': no {label} — bring-up timing cannot be verified"

    if threshold_v > nominal:
        return None, (f"rail '{name}': threshold {threshold_v}V is above the rail's own "
                      f"nominal {nominal}V — it never gets there")

    return delay + soft_start * (threshold_v / nominal), None


def check_sequence(spec: dict) -> list:
    failures = []
    rules = spec.get("rail_rules") or {}
    nets = nets_by_name(spec)

    for rule in rules.get("sequence") or []:
        name = rule.get("name", "<unnamed>")
        before, after = rule.get("before") or {}, rule.get("after") or {}
        margin = rule.get("min_margin_ms", 0.0)

        before_net = nets.get(before.get("rail"))
        after_net = nets.get(after.get("rail"))
        if before_net is None:
            failures.append(f"sequence '{name}': unknown rail '{before.get('rail')}'")
            continue
        if after_net is None:
            failures.append(f"sequence '{name}': unknown rail '{after.get('rail')}'")
            continue

        t_before, err_b = time_to_reach(before_net, before.get("reaches_v"))
        t_after, err_a = time_to_reach(after_net, after.get("reaches_v"))
        for err in (err_b, err_a):
            if err:
                failures.append(f"sequence '{name}': {err}")
        if t_before is None or t_after is None:
            continue

        actual = t_after - t_before
        if actual < margin:
            failures.append(
                f"sequence '{name}': {before_net['name']} reaches {before['reaches_v']}V at "
                f"{t_before:.3f} ms but {after_net['name']} reaches {after['reaches_v']}V at "
                f"{t_after:.3f} ms — margin {actual:.3f} ms is under the required {margin} ms"
            )
        else:
            print(f"  sequence: '{name}' holds with {actual:.3f} ms margin "
                  f"(requires {margin} ms)")

    return failures


CHECKS = {
    "budget": check_budget,
    "ramp": check_ramp,
    "sequence": check_sequence,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=pathlib.Path, default=POWER_SPEC,
                        help="power spec to check (default: io_specs/power.yaml)")
    parser.add_argument("--check", choices=sorted(CHECKS), action="append",
                        help="run only this check (repeatable; default: all)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    selected = args.check or sorted(CHECKS)

    failures = []
    for check_name in selected:
        failures.extend(f"[{check_name}] {f}" for f in CHECKS[check_name](spec))

    if failures:
        print("POWER RULES CHECK FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print(f"POWER RULES CHECK PASSED ({', '.join(selected)})")


if __name__ == "__main__":
    main()
