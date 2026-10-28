#!/usr/bin/env python3
"""Map every module onto UltraScale+ cells with yosys, and hold it to a budget.

Simulation says the RTL is correct. This says it fits, and that it is the kind
of RTL that fits -- which is a separate question that a student FPGA project
usually discovers far too late.

The target is the Kria K26 (Zynq UltraScale+), via `synth_xilinx -family xcup`.
This is a proxy for Vivado, chosen because it runs on a free GitHub runner:
the cell counts are honest (real LUT6, FDRE, RAMB36E2, DSP48E2 cells), but
placement and timing belong to the Vivado build (B1.5, B3.4), not to this gate.

What it gates on, per bench:

  1. `synth_xilinx` must succeed. Anything yosys cannot map to real
     UltraScale+ cells is a failure.
  2. `check -assert` must pass -- combinational loops, multiply-driven nets,
     undriven selects.
  3. Nothing generic may survive mapping. A `$`-prefixed cell left in the
     netlist means yosys gave up and left a soft-logic placeholder, which will
     fail or balloon later.
  4. The mapped size must stay inside `synth.budget` in bench.yaml, and the sum
     of all budgets must stay inside `utilization_ceiling` in rtl/target.yaml.

    python3 scripts/run_synth_check.py
    python3 scripts/run_synth_check.py --module fpga --only frame_crc
"""
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from rtl_bench import REPO_ROOT, BenchError, discover, load_target   # noqa: E402

# How UltraScale+ cells roll up into the numbers anyone actually budgets, with
# the weight of each cell in that bucket's unit. LUT RAM and shift registers
# are counted in the LUTs they occupy, because that is what they take from the
# fabric; block RAM is counted in 18 Kb halves, so a RAMB36E2 is two.
CELL_WEIGHTS = {
    "luts": {
        "LUT1": 1, "LUT2": 1, "LUT3": 1, "LUT4": 1, "LUT5": 1, "LUT6": 1,
        "LUT6_2": 1,
        "SRL16E": 1, "SRLC32E": 1,
        "RAM32X1S": 1, "RAM64X1S": 1, "RAM128X1S": 2, "RAM256X1S": 4,
        "RAM32X1D": 2, "RAM64X1D": 2, "RAM128X1D": 4,
        "RAM32M": 4, "RAM64M": 4, "RAM32M16": 8, "RAM64M8": 8,
    },
    "ff": {"FDRE": 1, "FDSE": 1, "FDCE": 1, "FDPE": 1},
    "bram18": {"RAMB18E2": 1, "RAMB36E2": 2, "FIFO18E2": 1, "FIFO36E2": 2},
    "uram": {"URAM288": 1},
    "dsp": {"DSP48E2": 1},
}
BUCKETS = ("luts", "ff", "bram18", "uram", "dsp")
BUCKET_LABEL = {
    "luts": "LUTs",
    "ff": "FFs",
    "bram18": "BRAM18",
    "uram": "URAM",
    "dsp": "DSPs",
}

STAT_CELL_RE = re.compile(r"^\s{4,}(\$?[A-Za-z_][\w$.]*)\s+(\d+)\s*$")


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def parse_stat(log: str, top: str):
    """Pull the per-cell counts out of the last `stat` block for `top`.

    Returns None if no statistics block for `top` was found at all, and a dict
    otherwise -- which may legitimately be empty, because a module that yosys
    optimises away entirely reports `Number of cells: 0`. Those two outcomes
    must stay distinguishable: the first means we are measuring the wrong thing
    and have to stop, the second means the module genuinely costs nothing yet.

    The LAST block, not the first: synth_xilinx prints statistics part-way
    through its own script, before mapping is finished, and reading that one
    would report soft logic as if it were the final netlist.
    """
    header = "=== %s ===" % top
    start = log.rfind(header)
    if start == -1:
        # yosys prefixes a hierarchy path on some flows.
        matches = [m.start() for m in re.finditer(r"^=== .*%s ===" % re.escape(top),
                                                  log, re.MULTILINE)]
        if not matches:
            return None
        start = matches[-1]

    cells = {}
    found_cell_count = False
    for line in log[start:].splitlines()[1:]:
        if line.startswith("==="):
            break
        if "Number of cells:" in line:
            found_cell_count = True
            continue
        if found_cell_count:
            match = STAT_CELL_RE.match(line)
            if match:
                cells[match.group(1)] = int(match.group(2))
            elif line.strip():
                break
    return cells if found_cell_count else None


def roll_up(cells: dict) -> dict:
    totals = {bucket: 0 for bucket in BUCKETS}
    for name, count in cells.items():
        for bucket, weights in CELL_WEIGHTS.items():
            if name in weights:
                totals[bucket] += count * weights[name]
                break
    return totals


def generic_cells(cells: dict) -> dict:
    return {name: count for name, count in cells.items() if name.startswith("$")}


def run_yosys(bench, build: pathlib.Path, target: dict) -> tuple:
    """Synthesize for UltraScale+. Returns (ok, log)."""
    build.mkdir(parents=True, exist_ok=True)
    json_out = build / ("%s.json" % bench.synth["top"])
    param_set = bench.param_set(bench.synth["param_set"])
    synth_command = target.get("device", {}).get("yosys_synth_command",
                                                 "synth_xilinx -family xcup")

    commands = ["read_verilog -sv %s"
                % " ".join(str(path) for path in bench.sources)]
    for name, value in (param_set.params if param_set else {}).items():
        commands.append("chparam -set %s %s %s" % (name, value, bench.synth["top"]))
    # -noiopad / -noclkbuf: a bench top is a leaf module inside the Vivado
    # design, not the chip boundary, so no I/O buffers or BUFGs belong in it.
    # The netlist is written separately: synth_xilinx in yosys 0.33 has no
    # -json option, unlike synth_ecp5.
    commands.append("%s -noiopad -noclkbuf -top %s"
                    % (synth_command, bench.synth["top"]))
    commands.append("write_json %s" % json_out)
    commands.append("stat -top %s" % bench.synth["top"])
    # check -assert is the gate; it exits non-zero on a real structural problem.
    commands.append("check -assert")

    completed = subprocess.run(
        ["yosys", "-p", "; ".join(commands)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    log = completed.stdout or ""
    (build / "yosys.log").write_text(log, encoding="utf-8", errors="replace")
    return completed.returncode == 0, log


def check_budget(bench, totals: dict) -> list:
    problems = []
    budget = bench.synth["budget"]
    for bucket, limit in budget.items():
        used = totals.get(bucket, 0)
        if used > limit:
            problems.append(
                "%s: %d used against a budget of %d (%+d). Either optimise, or "
                "raise synth.budget.%s in bench.yaml and say in the pull "
                "request what the extra area bought."
                % (BUCKET_LABEL.get(bucket, bucket), used, limit,
                   used - limit, bucket)
            )
    return problems


def check_ceiling(benches, target: dict) -> list:
    """The sum of declared budgets against the device, not the measured sum.

    Budgets are what we have promised ourselves each block may cost, so summing
    them catches the part running out before the last block is even written --
    which is the point at which it is still cheap to change the architecture.
    """
    resources = target.get("resources", {})
    ceiling = target.get("utilization_ceiling", {})
    totals = {bucket: 0 for bucket in BUCKETS}
    for bench in benches:
        if not bench.synth["enabled"]:
            continue
        for bucket, value in bench.synth["budget"].items():
            totals[bucket] += value

    problems = []
    for bucket, used in totals.items():
        capacity = resources.get(bucket)
        fraction = ceiling.get(bucket)
        if not capacity or not fraction:
            continue
        limit = capacity * fraction
        if used > limit:
            problems.append(
                "declared %s budgets total %d, over the %.0f%% ceiling of %d "
                "for %s (%d). The part is being spent faster than it is being "
                "written -- revisit the architecture before adding more."
                % (BUCKET_LABEL.get(bucket, bucket), used, fraction * 100,
                   int(limit), target.get("device", {}).get("part_number", "the part"),
                   capacity)
            )
    return problems, totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module", help="only benches under rtl_tests/<module>/")
    parser.add_argument("--only", help="only the bench with this name")
    parser.add_argument("--skip-ceiling", action="store_true",
                        help="do not check the summed budgets against the device")
    args = parser.parse_args()

    if not tool_available("yosys"):
        print("SYNTH CHECK FAILED: yosys is not installed. Run this inside the "
              "container built with --target synth (`tools/dev synth`).")
        return 1

    try:
        target = load_target()
        all_benches = discover()
        selected = discover(module=args.module, only=args.only)
    except BenchError as exc:
        print("BENCH MANIFEST ERROR: %s" % exc)
        return 1

    if not selected:
        print("No benches matched (module=%r only=%r)." % (args.module, args.only))
        return 1

    device = target.get("device", {})
    print("Target: %s  (%s)\n" % (device.get("part_number"), device.get("family")))

    failures = []
    rows = []
    for bench in selected:
        if not bench.synth["enabled"]:
            print("[skip] %s/%s (synth disabled in bench.yaml)"
                  % (bench.module, bench.name))
            continue
        if bench.status == "blocked":
            print("[skip] %s/%s (blocked: %s)"
                  % (bench.module, bench.name, bench.blocked_reason))
            continue

        build = REPO_ROOT / "build" / "synth" / bench.module / bench.name
        ok, log = run_yosys(bench, build, target)
        if not ok:
            tail = "\n".join(log.strip().splitlines()[-30:])
            failures.append((bench, "yosys failed:\n%s" % tail))
            print("[FAIL] %s/%s -- yosys failed" % (bench.module, bench.name))
            continue

        cells = parse_stat(log, bench.synth["top"])
        if cells is None:
            failures.append((bench, (
                "could not find a `stat` block for top %r in the yosys log. "
                "Check that synth.top names a module that actually exists."
                % bench.synth["top"])))
            print("[FAIL] %s/%s -- no statistics" % (bench.module, bench.name))
            continue

        problems = []
        leftovers = generic_cells(cells)
        if leftovers:
            problems.append(
                "generic cells survived UltraScale+ mapping: %s. yosys could not "
                "map this to the fabric -- usually an unsupported construct or a "
                "memory it could not infer."
                % ", ".join("%s x%d" % kv for kv in sorted(leftovers.items()))
            )

        totals = roll_up(cells)
        problems.extend(check_budget(bench, totals))

        used = "  ".join("%s %d" % (BUCKET_LABEL[b], totals[b]) for b in BUCKETS)
        rows.append((bench, totals))
        if problems:
            failures.append((bench, "\n".join(problems)))
            print("[FAIL] %s/%s  %s" % (bench.module, bench.name, used))
        else:
            print("[ok  ] %s/%s  %s" % (bench.module, bench.name, used))

    ceiling_problems, declared = ([], {})
    if not args.skip_ceiling and not (args.module or args.only):
        ceiling_problems, declared = check_ceiling(all_benches, target)

    summary = ["| Module | LUTs | FFs | BRAM18 | URAM | DSPs | Budget LUTs |",
               "|---|---:|---:|---:|---:|---:|---:|"]
    for bench, totals in rows:
        summary.append("| `%s/%s` | %d | %d | %d | %d | %d | %s |" % (
            bench.module, bench.name, totals["luts"], totals["ff"],
            totals["bram18"], totals["uram"], totals["dsp"],
            bench.synth["budget"].get("luts", "-")))
    if declared:
        resources = target.get("resources", {})
        summary.append("| **declared budgets total** | %d | %d | %d | %d | %d | of %s |"
                       % (declared["luts"], declared["ff"], declared["bram18"],
                          declared["uram"], declared["dsp"],
                          resources.get("luts", "?")))
    table = "\n".join(summary) + "\n"

    out_dir = REPO_ROOT / "build" / "synth"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.md").write_text(table, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("## UltraScale+ synthesis (%s)\n\n%s\n"
                         % (device.get("part_number", "?"), table))

    print("\n" + table)

    if failures or ceiling_problems:
        print("SYNTH CHECK FAILED:")
        for bench, message in failures:
            print("\n--- %s/%s ---\n%s" % (bench.module, bench.name, message))
        for problem in ceiling_problems:
            print("\n--- device ceiling ---\n%s" % problem)
        return 1

    print("SYNTH CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
