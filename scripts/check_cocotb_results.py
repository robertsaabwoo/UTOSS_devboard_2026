#!/usr/bin/env python3
"""Fail the build if a cocotb run reported failures -- or reported nothing.

cocotb's Makefile flow exits 0 even when testcases fail, so `make SIM=...`
on its own is NOT a usable CI gate: a broken DUT would sail through green.
The run's JUnit XML is the real source of truth, so this parses it.

Also treats "no testcases at all" as a failure. A mistyped MODULE, a renamed
testbench, or a collection error would otherwise produce an empty result set
that is indistinguishable from success -- the worst kind of silent pass.
"""
import argparse
import pathlib
import sys
import xml.etree.ElementTree as ET


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=pathlib.Path, help="path to cocotb results.xml")
    args = parser.parse_args()

    if not args.results.is_file():
        print(
            f"COCOTB RESULTS CHECK FAILED: {args.results} not found — the simulation "
            "produced no result file (compile error, crash, or it never ran)."
        )
        sys.exit(1)

    try:
        root = ET.parse(args.results).getroot()
    except ET.ParseError as exc:
        print(f"COCOTB RESULTS CHECK FAILED: {args.results} is not valid XML: {exc}")
        sys.exit(1)

    testcases = root.findall(".//testcase")
    if not testcases:
        print(
            f"COCOTB RESULTS CHECK FAILED: {args.results} contains no testcases — "
            "nothing ran (check MODULE / TOPLEVEL in the Makefile)."
        )
        sys.exit(1)

    failures = []
    for case in testcases:
        name = f"{case.get('classname', '?')}.{case.get('name', '?')}"
        for bad in case.findall("failure") + case.findall("error"):
            failures.append(f"{name}: {bad.get('message') or bad.tag}")

    print(f"{len(testcases)} cocotb testcase(s) reported in {args.results}")

    if failures:
        print("\nCOCOTB RESULTS CHECK FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("COCOTB RESULTS CHECK PASSED")


if __name__ == "__main__":
    main()
