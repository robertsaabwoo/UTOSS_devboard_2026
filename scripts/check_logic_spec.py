#!/usr/bin/env python3
"""Static logic/electrical cross-check across io_specs/*.yaml.

For every net with a `source:` reference, verify the driving net's
electrical characteristics satisfy the receiving net's requirements.
Pure spec-level check -- no SPICE simulation, no schematic parsing.

Modules are discovered from io_specs/*.yaml's own `block:` field, not a
hardcoded list, so a new module (cpu, memory, ...) plugs in by dropping a
new spec file -- no changes to this script.
"""
import argparse
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
IO_SPECS_DIR = ROOT / "io_specs"


def load_all_specs() -> dict:
    specs = {}
    for path in sorted(IO_SPECS_DIR.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text())
        specs[spec["block"]] = spec
    return specs


def net_lookup(specs: dict, module: str, net_name: str):
    spec = specs.get(module)
    if spec is None:
        return None
    for net in spec.get("nets", []):
        if net["name"] == net_name:
            return net
    return None


def check_rail_edge(sink_module: str, sink_net: dict, source_module: str, source_net: dict) -> list:
    failures = []
    prefix = f"{sink_module}.{sink_net['name']} (source {source_module}.{source_net['name']})"

    sink_min, sink_max = sink_net.get("min_v"), sink_net.get("max_v")
    if sink_min is None or sink_max is None:
        failures.append(f"{prefix}: sink net is missing min_v/max_v — cannot verify against source rail")
        return failures

    source_min, source_max = source_net.get("min_v"), source_net.get("max_v")
    if source_min is None or source_max is None:
        failures.append(f"{prefix}: source net is missing min_v/max_v — cannot verify")
        return failures

    if source_min < sink_min:
        failures.append(f"{prefix}: source worst-case low {source_min}V is below sink's accepted min {sink_min}V")
    if source_max > sink_max:
        failures.append(f"{prefix}: source worst-case high {source_max}V exceeds sink's accepted max {sink_max}V")

    return failures


def check_logic_edge(sink_module: str, sink_net: dict, source_module: str, source_net: dict) -> list:
    failures = []
    prefix = f"{sink_module}.{sink_net['name']} (source {source_module}.{source_net['name']})"

    sink_elec = sink_net.get("electrical", {})
    source_elec = source_net.get("electrical", {})
    require = sink_elec.get("require")
    drive = source_elec.get("drive")

    if require is None:
        failures.append(f"{prefix}: sink net has no electrical.require block — cannot verify logic levels")
        return failures
    if drive is None:
        failures.append(f"{prefix}: source net has no electrical.drive block — cannot verify logic levels")
        return failures

    voh_min, vol_max = drive.get("voh_min_v"), drive.get("vol_max_v")
    vih_min, vil_max = require.get("vih_min_v"), require.get("vil_max_v")

    if voh_min is not None and vih_min is not None and voh_min < vih_min:
        failures.append(f"{prefix}: driver VOH_min {voh_min}V is below sink VIH_min {vih_min}V — logic-high not recognized")
    if vol_max is not None and vil_max is not None and vol_max > vil_max:
        failures.append(f"{prefix}: driver VOL_max {vol_max}V exceeds sink VIL_max {vil_max}V — logic-low not recognized")

    driver_high_swing = drive.get("voh_max_v", source_net.get("logic_level_v"))
    absolute_max = sink_net.get("absolute_max_v", sink_elec.get("absolute_max_v"))
    if driver_high_swing is not None and absolute_max is not None and driver_high_swing > absolute_max:
        failures.append(f"{prefix}: driver worst-case high {driver_high_swing}V exceeds sink absolute max {absolute_max}V — overvoltage risk")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", help="only report/fail on edges touching this module")
    args = parser.parse_args()

    specs = load_all_specs()
    all_failures = []

    for module, spec in specs.items():
        for net in spec.get("nets", []):
            source_ref = net.get("source")
            if not source_ref:
                continue

            source_module, source_net_name = source_ref.split(".", 1)
            source_net = net_lookup(specs, source_module, source_net_name)
            if source_net is None:
                if args.module and args.module not in (module, source_module):
                    continue
                all_failures.append(f"{module}.{net['name']}: source '{source_ref}' does not resolve to a known net")
                continue

            if args.module and args.module not in (module, source_module):
                continue

            if net.get("type") == "rail":
                all_failures.extend(check_rail_edge(module, net, source_module, source_net))
            elif net.get("type") == "logic":
                all_failures.extend(check_logic_edge(module, net, source_module, source_net))

    if all_failures:
        print("LOGIC/ELECTRICAL SPEC CHECK FAILED:")
        for f in all_failures:
            print(f"  - {f}")
        sys.exit(1)

    scope = f" (scope: {args.module})" if args.module else " (full board)"
    print(f"LOGIC/ELECTRICAL SPEC CHECK PASSED{scope}")


if __name__ == "__main__":
    main()
