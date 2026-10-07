#!/usr/bin/env python3
"""Fail the build if a cocotb run reported failures -- or reported nothing.

cocotb's Makefile flow exits 0 even when testcases fail, so `make SIM=...`
on its own is NOT a usable CI gate: a broken DUT would sail through green.
The run's JUnit XML is the real source of truth, so this parses it.

Also treats "no testcases at all" as a failure. A mistyped MODULE, a renamed
testbench, or a collection error would otherwise produce an empty result set
that is indistinguishable from success -- the worst kind of silent pass.

Usable two ways:
  * CLI, one results file per invocation (what the hardware CI job does)
  * imported, via evaluate(), by scripts/run_rtl_tests.py -- which is why the
    parsing lives in one place instead of two that drift apart
"""
import argparse
import pathlib
import sys
import xml.etree.ElementTree as ET
from typing import List, NamedTuple


class Result(NamedTuple):
    ok: bool
    testcases: int
    failures: List[str]
    error: str = ""


def evaluate(results: pathlib.Path) -> Result:
    """Parse a cocotb results.xml. Never raises; reports problems in Result."""
    if not results.is_file():
        return Result(False, 0, [], (
            f"{results} not found -- the simulation produced no result file "
            "(compile error, crash, or it never ran)."
        ))

    try:
        root = ET.parse(results).getroot()
    except ET.ParseError as exc:
        return Result(False, 0, [], f"{results} is not valid XML: {exc}")

    testcases = root.findall(".//testcase")
    if not testcases:
        return Result(False, 0, [], (
            f"{results} contains no testcases -- nothing ran (check the "
            "`testbench` and `toplevel` fields in bench.yaml)."
        ))

    failures = []
    for case in testcases:
        name = f"{case.get('classname', '?')}.{case.get('name', '?')}"
        for bad in case.findall("failure") + case.findall("error"):
            failures.append(f"{name}: {bad.get('message') or bad.tag}")

    return Result(not failures, len(testcases), failures)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=pathlib.Path, help="path to cocotb results.xml")
    args = parser.parse_args()

    result = evaluate(args.results)

    if result.error:
        print(f"COCOTB RESULTS CHECK FAILED: {result.error}")
        sys.exit(1)

    print(f"{result.testcases} cocotb testcase(s) reported in {args.results}")

    if result.failures:
        print("\nCOCOTB RESULTS CHECK FAILED:")
        for failure in result.failures:
            print(f"  - {failure}")
        sys.exit(1)

    print("COCOTB RESULTS CHECK PASSED")


if __name__ == "__main__":
    main()
