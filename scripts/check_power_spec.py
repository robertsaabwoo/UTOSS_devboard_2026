#!/usr/bin/env python3
"""Run the power submodule SPICE testbench and check rails against io_specs/power.yaml."""
import re
import subprocess
import sys
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "io_specs" / "power.yaml"
TESTBENCH = ROOT / "spice" / "power" / "testbench.cir"

# SPICE node name -> io_specs net name
NODE_TO_NET = {"PLUS5V": "+5V", "PLUS3V3": "+3V3"}


def run_ngspice() -> str:
    result = subprocess.run(
        ["ngspice", "-b", TESTBENCH.name],
        cwd=TESTBENCH.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout + "\n" + result.stderr


def parse_voltage(output: str, node: str) -> float | None:
    match = re.search(rf"{node.lower()}\s*=\s*([-\d.eE+]+)", output.lower())
    return float(match.group(1)) if match else None


def main() -> None:
    spec = yaml.safe_load(SPEC_PATH.read_text())
    nets_by_name = {n["name"]: n for n in spec["nets"]}

    output = run_ngspice()
    failures = []

    for node, net_name in NODE_TO_NET.items():
        voltage = parse_voltage(output, node)
        if voltage is None:
            failures.append(f"{net_name}: could not parse simulated voltage from ngspice output for node {node}")
            continue

        net_spec = nets_by_name.get(net_name)
        if net_spec is None:
            failures.append(f"{net_name}: no matching entry in io_specs/power.yaml")
            continue

        min_v, max_v = net_spec.get("min_v"), net_spec.get("max_v")
        print(f"{net_name}: simulated {voltage:.4f} V (spec {min_v}-{max_v} V)")

        if min_v is not None and voltage < min_v:
            failures.append(f"{net_name}: simulated {voltage:.4f}V is below spec min {min_v}V")
        if max_v is not None and voltage > max_v:
            failures.append(f"{net_name}: simulated {voltage:.4f}V is above spec max {max_v}V")

    if failures:
        print("\nSPICE VERIFY FAILED:")
        for f in failures:
            print(f"  - {f}")
        print("\n--- full ngspice output (for debugging) ---")
        print(output)
        sys.exit(1)

    print("\nSPICE VERIFY PASSED")


if __name__ == "__main__":
    main()
