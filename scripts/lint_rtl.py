#!/usr/bin/env python3
"""Static lint gate for all RTL, via `verilator --lint-only`.

Verilator is used here purely as a linter -- nothing is simulated. It is far
stricter than Icarus about the things that cost FPGA teams weeks:

  * implicit width truncation and extension (WIDTHEXPAND / WIDTHTRUNC)
  * an inferred latch where a flop was intended (LATCH) -- the single most
    common way a design that simulates correctly fails in hardware
  * a signal that is read but never driven, or driven twice (UNDRIVEN, MULTIDRIVEN)
  * a combinational loop (UNOPTFLAT)
  * a module whose name does not match its filename (DECLFILENAME), which
    breaks every file-based tool downstream

It also enforces a coverage rule: every .v/.sv file under rtl/ must be listed
in some bench.yaml's `sources`. An RTL file nobody compiles is an RTL file
nobody tests, and it will not be discovered until integration.

    python3 scripts/lint_rtl.py
    python3 scripts/lint_rtl.py --module fpga
"""
import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from rtl_bench import REPO_ROOT, BenchError, discover   # noqa: E402

RTL_DIR = REPO_ROOT / "rtl"
RTL_SUFFIXES = (".v", ".sv")

# Waived for the whole repo, with reasons. Anything not listed here must be
# waived per bench in bench.yaml, with a reason, and justified in review.
GLOBAL_WAIVERS = [
    # A parameterized library module legitimately has parameters that some
    # configurations do not use (a generate branch that is not taken). This is
    # the one warning that fires often enough on correct code to train people
    # to ignore lint output entirely, which is worse than the warning.
    "UNUSEDPARAM",
]


def verilator_available() -> bool:
    try:
        subprocess.run(["verilator", "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _waiver_flags(bench) -> list:
    flags = ["-Wno-" + code for code in GLOBAL_WAIVERS]
    for waiver in bench.lint["waivers"]:
        # Accept either "CODE" or {code: CODE, reason: ...}
        code = waiver["code"] if isinstance(waiver, dict) else waiver
        flags.append("-Wno-" + str(code))
    return flags


def _lint_tops(bench) -> list:
    """Every module in this bench that must be linted as a top in its own right.

    Linting only `lint.top` is not enough: verilator elaborates just the
    hierarchy under the top, so a module that is listed in `sources` but not
    instantiated anywhere under it is parsed and then ignored -- an inferred
    latch inside it is never reported. That is exactly the module nobody has
    integrated yet, which is the one most likely to have the bug.

    So each source file is also linted as its own top. The module name is taken
    from the filename, which is enforced elsewhere by DECLFILENAME and by the
    one-module-per-file rule in rtl/README.md; if they disagree, verilator says
    it cannot find the top module, which is the correct complaint.
    """
    tops = [bench.lint["top"]]
    for path in bench.sources:
        if path.suffix not in RTL_SUFFIXES:
            continue    # headers and `include fragments have no top
        if path.stem not in tops:
            tops.append(path.stem)
    return tops


def lint_bench(bench) -> tuple:
    """Lint one bench, once per module. Returns (ok, output)."""
    sources = [str(path) for path in bench.sources]
    waivers = _waiver_flags(bench)
    ok = True
    chunks = []
    for top in _lint_tops(bench):
        command = (["verilator", "--lint-only", "-Wall", "--top-module", top]
                   + waivers + sources)
        completed = subprocess.run(command, cwd=str(REPO_ROOT),
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        output = completed.stdout or ""
        if completed.returncode != 0:
            ok = False
        if output.strip():
            chunks.append("--- as top: %s ---\n%s" % (top, output.rstrip()))
    return ok, "\n".join(chunks)


def check_coverage(benches) -> list:
    """Every RTL file must be compiled by at least one bench."""
    covered = set()
    for bench in benches:
        for path in bench.sources:
            covered.add(path.resolve())

    orphans = []
    if RTL_DIR.is_dir():
        for path in sorted(RTL_DIR.rglob("*")):
            if path.suffix not in RTL_SUFFIXES or not path.is_file():
                continue
            if any(part.startswith("_") for part in path.relative_to(RTL_DIR).parts):
                continue   # rtl/**/_template/ and friends
            if path.resolve() not in covered:
                orphans.append(path.relative_to(REPO_ROOT).as_posix())
    return orphans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module", help="only benches under rtl_tests/<module>/")
    parser.add_argument("--only", help="only the bench with this name")
    parser.add_argument("--skip-coverage", action="store_true",
                        help="do not require every rtl/ file to belong to a bench "
                             "(only valid with --module or --only, where the "
                             "selection is partial by construction)")
    args = parser.parse_args()

    if not verilator_available():
        print("LINT FAILED: verilator is not installed. Run this inside the "
              "container (`tools/dev lint`) or install verilator.")
        return 1

    try:
        all_benches = discover()
        selected = discover(module=args.module, only=args.only)
    except BenchError as exc:
        print("BENCH MANIFEST ERROR: %s" % exc)
        return 1

    if not selected:
        print("No benches matched (module=%r only=%r)." % (args.module, args.only))
        return 1

    failures = []
    for bench in selected:
        if not bench.lint["enabled"]:
            print("[skip] %s/%s (lint disabled in bench.yaml)"
                  % (bench.module, bench.name))
            continue
        if bench.status == "blocked":
            print("[skip] %s/%s (blocked: %s)"
                  % (bench.module, bench.name, bench.blocked_reason))
            continue
        ok, output = lint_bench(bench)
        print("[%s] %s/%s" % ("ok  " if ok else "FAIL", bench.module, bench.name))
        if not ok:
            failures.append((bench, output))
        elif output.strip():
            # Verilator can print notes while still exiting 0; show them.
            print(output.rstrip())

    orphans = [] if (args.skip_coverage or args.module or args.only) \
        else check_coverage(all_benches)

    if failures:
        print("\nLINT FAILED:")
        for bench, output in failures:
            print("\n--- %s/%s (%s) ---" % (bench.module, bench.name, bench.rel_dir))
            print(output.rstrip())
        print("\nFix the warning, or -- if it is genuinely wrong -- add the code "
              "to `lint.waivers` in that bench's bench.yaml with a reason.")
        return 1

    if orphans:
        print("\nLINT FAILED: RTL files not compiled by any bench:")
        for path in orphans:
            print("  - %s" % path)
        print("\nEvery module needs a bench. Add the file to the `sources` of "
              "the bench that exercises it, or create one with "
              "`python3 scripts/new_module.py`.")
        return 1

    print("\nLINT PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
