#!/usr/bin/env python3
"""Discover every cocotb bench under rtl_tests/ and run it.

This is the whole contract for a contributor: drop a directory under
rtl_tests/<module>/<name>/ containing a bench.yaml and a testbench, and it
runs here and in CI. Nothing else to register, no CI file to edit.

    python3 scripts/run_rtl_tests.py                 # everything
    python3 scripts/run_rtl_tests.py --module fpga    # one module group
    python3 scripts/run_rtl_tests.py --only dcmi_rx   # one bench
    python3 scripts/run_rtl_tests.py --strict         # wip counts as a failure

Why this exists rather than a Makefile per bench: a per-bench Makefile has to
be remembered, and the one thing CI must never do is quietly run nothing. Every
bench is discovered, every discovered bench is accounted for in the summary,
and a bench that produces no testcases is a failure rather than a pass.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from check_cocotb_results import evaluate                      # noqa: E402
from rtl_bench import REPO_ROOT, BenchError, discover          # noqa: E402

COCOTB_MK = REPO_ROOT / "rtl_tests" / "common" / "cocotb.mk"
TB_HELPERS = REPO_ROOT / "rtl_tests" / "common"


class RunOutcome:
    def __init__(self, bench, param_set, state, detail="", testcases=0,
                 seconds=0.0, log=None):
        self.bench = bench
        self.param_set = param_set
        self.state = state          # pass | fail | blocked | wip-fail
        self.detail = detail
        self.testcases = testcases
        self.seconds = seconds
        self.log = log

    @property
    def label(self):
        return "%s/%s[%s]" % (self.bench.module, self.bench.name, self.param_set)


def compile_args(bench, param_set):
    """Simulator flags that apply this parameter set and these defines.

    Parameters are overridden on the compiler command line rather than by
    editing the RTL, which is what makes a width-parameterized module provably
    width-parameterized: the same source is elaborated at several widths.
    """
    args = []
    if bench.simulator == "icarus":
        for name, value in param_set.params.items():
            args.append("-P%s.%s=%s" % (bench.toplevel, name, value))
        for name, value in bench.defines.items():
            args.append("-D%s=%s" % (name, value))
    elif bench.simulator == "verilator":
        for name, value in param_set.params.items():
            args.append("-G%s=%s" % (name, value))
        for name, value in bench.defines.items():
            args.append("+define+%s=%s" % (name, value))
    else:
        raise BenchError(
            "%s: simulator=%r is not supported (icarus, verilator)"
            % (bench.rel_dir, bench.simulator)
        )
    return args


def run_one(bench, param_set, waves=False, verbose=False) -> RunOutcome:
    build = bench.build_dir(param_set.name)
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True, exist_ok=True)

    results = build / "results.xml"
    log_path = build / "sim.log"

    sources = " ".join(str(p) for p in bench.sources)
    command = [
        "make", "-f", str(COCOTB_MK),
        "SIM=%s" % bench.simulator,
        "TOPLEVEL=%s" % bench.toplevel,
        "TOPLEVEL_LANG=verilog",
        "MODULE=%s" % bench.testbench,
        "VERILOG_SOURCES=%s" % sources,
        "SIM_BUILD=%s" % (build / "sim_build"),
        "COCOTB_RESULTS_FILE=%s" % results,
        "COMPILE_ARGS=%s" % " ".join(compile_args(bench, param_set)),
    ]
    if waves:
        command.append("WAVES=1")

    env = dict(os.environ)
    # The bench directory first so `import utoss_tb` resolves to the shared
    # helpers, and a bench-local module can still shadow one deliberately.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(bench.dir), str(TB_HELPERS), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Hand the parameter set to the bench as well as to the compiler, so a
    # bench can assert that the override actually took effect. Without this a
    # silently-dropped -P flag means every parameter set elaborates at the
    # default width and the sweep proves nothing -- see
    # rtl_tests/common/utoss_tb/params.py.
    env["UTOSS_PARAM_SET"] = param_set.name
    for name, value in param_set.params.items():
        env["UTOSS_PARAM_" + str(name)] = str(value)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=str(bench.dir), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=bench.timeout_seconds, text=True,
        )
        output = completed.stdout or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        timed_out = True

    elapsed = time.monotonic() - started
    log_path.write_text(output, encoding="utf-8", errors="replace")
    if verbose:
        print(output)

    if timed_out:
        return RunOutcome(
            bench, param_set.name, "fail",
            testcases=0, seconds=elapsed, log=log_path,
            detail=("simulation exceeded timeout_seconds=%d and was killed. A "
                    "hung bench is a failure: add a cocotb timeout to the test "
                    "or fix the DUT handshake that never completes."
                    % bench.timeout_seconds),
        )

    result = evaluate(results)
    if result.error:
        return RunOutcome(bench, param_set.name, "fail", detail=result.error,
                          seconds=elapsed, log=log_path)
    if result.failures:
        detail = "; ".join(result.failures[:4])
        if len(result.failures) > 4:
            detail += " (+%d more)" % (len(result.failures) - 4)
        return RunOutcome(bench, param_set.name, "fail", detail=detail,
                          testcases=result.testcases, seconds=elapsed,
                          log=log_path)
    return RunOutcome(bench, param_set.name, "pass", testcases=result.testcases,
                      seconds=elapsed, log=log_path)


def summary_table(outcomes):
    header = ("| Bench | Params | Status | Tests | Time | Detail |\n"
              "|---|---|---|---|---:|---|\n")
    icon = {"pass": "pass", "fail": "FAIL", "wip-fail": "FAIL (wip)",
            "blocked": "blocked"}
    rows = []
    for outcome in outcomes:
        detail = outcome.detail.replace("|", "\\|").replace("\n", " ")
        if len(detail) > 160:
            detail = detail[:157] + "..."
        rows.append("| `%s/%s` | %s | %s | %d | %.1fs | %s |" % (
            outcome.bench.module, outcome.bench.name, outcome.param_set,
            icon.get(outcome.state, outcome.state), outcome.testcases,
            outcome.seconds, detail))
    return header + "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module", help="only benches under rtl_tests/<module>/")
    parser.add_argument("--only", help="only the bench with this name")
    parser.add_argument("--param-set", help="only this parameter set")
    parser.add_argument("--strict", action="store_true",
                        help="treat status: wip as a failure (CI uses this on "
                             "pull requests into main)")
    parser.add_argument("--waves", action="store_true",
                        help="dump waveforms into the build directory")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="stream simulator output instead of only logging it")
    parser.add_argument("--list", action="store_true",
                        help="list what would run and exit")
    args = parser.parse_args()

    try:
        benches = discover(module=args.module, only=args.only)
    except BenchError as exc:
        print("BENCH MANIFEST ERROR: %s" % exc)
        return 1

    if not benches:
        # Not a pass. An empty selection means the filter was wrong or a bench
        # was deleted, and either way CI must not report success.
        print("No benches matched (module=%r only=%r). Nothing ran, which is "
              "treated as a failure -- check the filter, or "
              "`python3 scripts/rtl_bench.py` to list what exists."
              % (args.module, args.only))
        return 1

    if args.list:
        for bench in benches:
            for param_set in bench.param_sets:
                print("%s/%s[%s] status=%s"
                      % (bench.module, bench.name, param_set.name, bench.status))
        return 0

    outcomes = []
    for bench in benches:
        if bench.status == "blocked":
            print("[blocked] %s/%s -- %s"
                  % (bench.module, bench.name, bench.blocked_reason))
            outcomes.append(RunOutcome(bench, "-", "blocked",
                                       detail=bench.blocked_reason))
            continue

        for param_set in bench.param_sets:
            if args.param_set and param_set.name != args.param_set:
                continue
            print("[run]     %s/%s[%s] %s"
                  % (bench.module, bench.name, param_set.name,
                     "(wip)" if bench.status == "wip" else ""))
            try:
                outcome = run_one(bench, param_set, waves=args.waves,
                                  verbose=args.verbose)
            except BenchError as exc:
                outcome = RunOutcome(bench, param_set.name, "fail", detail=str(exc))
            if outcome.state == "fail" and bench.status == "wip" and not args.strict:
                outcome.state = "wip-fail"
            outcomes.append(outcome)
            print("          -> %s  %d test(s)  %.1fs%s"
                  % (outcome.state, outcome.testcases, outcome.seconds,
                     ("  " + outcome.detail) if outcome.detail else ""))

    if not outcomes:
        # Same reasoning as the empty-selection case above: a --param-set that
        # matches nothing must not look like a clean run.
        print("No bench/parameter-set combination matched (param_set=%r). "
              "Nothing ran." % args.param_set)
        return 1

    hard_failures = [o for o in outcomes if o.state == "fail"]
    soft_failures = [o for o in outcomes if o.state == "wip-fail"]
    blocked = [o for o in outcomes if o.state == "blocked"]
    passed = [o for o in outcomes if o.state == "pass"]

    table = summary_table(outcomes)
    out_dir = REPO_ROOT / "build" / "rtl"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.md").write_text(table, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("## RTL simulation\n\n" + table + "\n")

    print("\n" + table)
    print("%d passed, %d failed, %d wip-failed, %d blocked"
          % (len(passed), len(hard_failures), len(soft_failures), len(blocked)))

    if args.strict:
        wip = sorted(set(o.bench.rel_dir for o in outcomes
                         if o.bench.status == "wip"))
        if wip:
            print("\nSTRICT: these benches are still status: wip and cannot be "
                  "merged into main:")
            for item in wip:
                print("  - %s/bench.yaml" % item)
            return 1

    if hard_failures:
        print("\nRTL SIMULATION FAILED:")
        for outcome in hard_failures:
            print("  - %s: %s" % (outcome.label, outcome.detail))
            if outcome.log:
                print("    log: %s"
                      % outcome.log.relative_to(REPO_ROOT).as_posix())
        return 1

    if soft_failures:
        print("\nWIP benches failed (not fatal on this branch; they will block "
              "a pull request into main):")
        for outcome in soft_failures:
            print("  - %s: %s" % (outcome.label, outcome.detail))

    print("\nRTL SIMULATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
