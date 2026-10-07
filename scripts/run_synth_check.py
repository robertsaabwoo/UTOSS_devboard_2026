#!/usr/bin/env python3
"""Map every module onto the real ECP5 with yosys, and hold it to a budget.

Simulation says the RTL is correct. This says it fits, and that it is the kind
of RTL that fits -- which is a separate question that a student FPGA project
usually discovers far too late.

What it gates on, per bench:

  1. `synth_ecp5` must succeed. Anything yosys cannot map to real ECP5 cells is
     a failure, including a memory it cannot infer into an EBR and a primitive
     that does not exist on this part.
  2. `check -assert` must pass -- combinational loops, multiply-driven nets,
     undriven selects.
  3. Nothing generic may survive mapping. A `$`-prefixed cell left in the
     netlist means yosys gave up and left a soft-logic placeholder, which will
     fail or balloon later.
  4. The mapped size must stay inside `synth.budget` in bench.yaml, and the sum
     of all budgets must stay inside `utilization_ceiling` in
     rtl/ecp5_target.yaml. Routing and timing on an ECP5 degrade sharply in the
     last quarter of the part.

Place-and-route (nextpnr-ecp5) runs only for benches with `synth.place: true`
-- the top level. P&R on a leaf module in isolation produces a timing number
that has nothing to do with the timing that module will see in the assembled
design, and costs minutes to produce.

    python3 scripts/run_synth_check.py
    python3 scripts/run_synth_check.py --module fpga --only dcmi_rx
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

# How ECP5 cell names roll up into the four numbers anyone actually budgets.
# Several spellings per bucket on purpose: yosys renamed the LUT cell between
# 0.33 and later releases, and a pinned container today is an unpinned one in
# somebody's local install tomorrow.
CELL_BUCKETS = {
    "luts": ("LUT4", "TRELLIS_COMB", "TRELLIS_LUT4", "CCU2C"),
    "ff": ("TRELLIS_FF", "FD1P3AX", "FD1P3AY", "FD1P3BX", "FD1P3DX", "FD1S3AX"),
    "block_ram_blocks": ("DP16KD", "PDPW16KD", "SP16KD", "DP8KC", "PDPW8KC"),
    "dsp_mult_18x18": ("MULT18X18D", "MULT18X36D", "MULT9X9D", "ALU54A", "ALU24B"),
}
BUCKET_LABEL = {
    "luts": "LUTs",
    "ff": "FFs",
    "block_ram_blocks": "EBRs",
    "dsp_mult_18x18": "DSPs",
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

    The LAST block, not the first: synth_ecp5 prints statistics part-way
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
    totals = {bucket: 0 for bucket in CELL_BUCKETS}
    for name, count in cells.items():
        for bucket, prefixes in CELL_BUCKETS.items():
            if name in prefixes:
                totals[bucket] += count
                break
    return totals


def generic_cells(cells: dict) -> dict:
    return {name: count for name, count in cells.items() if name.startswith("$")}


def run_yosys(bench, build: pathlib.Path) -> tuple:
    """Synthesize for ECP5. Returns (ok, log, json_path)."""
    build.mkdir(parents=True, exist_ok=True)
    json_out = build / ("%s.json" % bench.synth["top"])
    param_set = bench.param_set(bench.synth["param_set"])

    commands = ["read_verilog -sv %s"
                % " ".join(str(path) for path in bench.sources)]
    for name, value in (param_set.params if param_set else {}).items():
        commands.append("chparam -set %s %s %s" % (name, value, bench.synth["top"]))
    commands.append("synth_ecp5 -top %s -json %s" % (bench.synth["top"], json_out))
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
    return completed.returncode == 0, log, json_out


def run_nextpnr(bench, build: pathlib.Path, json_path: pathlib.Path,
                target: dict) -> tuple:
    """Place and route. Returns (state, message) where state is ok|fail|skip."""
    if not tool_available("nextpnr-ecp5"):
        return "skip", ("nextpnr-ecp5 is not installed in this image; "
                        "place-and-route not attempted")

    lpf = bench.synth.get("lpf")
    if not lpf:
        return "fail", ("synth.place is true but no `lpf` is set. Place-and-route "
                        "without pin constraints places I/O wherever it likes, "
                        "which produces a timing number for a pinout we are not "
                        "building. Add the .lpf.")
    lpf_path = REPO_ROOT / lpf
    if not lpf_path.is_file():
        return "fail", "synth.lpf=%s does not exist" % lpf

    device = target.get("device", {})
    command = [
        "nextpnr-ecp5",
        device.get("nextpnr_device_flag", "--45k"),
        "--package", str(device.get("nextpnr_package", "CABGA381")),
        "--json", str(json_path),
        "--lpf", str(lpf_path),
        "--textcfg", str(build / "out.cfg"),
    ]
    target_mhz = bench.synth.get("target_mhz")
    if target_mhz:
        command += ["--freq", str(target_mhz)]

    completed = subprocess.run(command, cwd=str(REPO_ROOT),
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    log = completed.stdout or ""
    (build / "nextpnr.log").write_text(log, encoding="utf-8", errors="replace")

    if completed.returncode != 0:
        tail = "\n".join(log.strip().splitlines()[-25:])
        return "fail", "nextpnr-ecp5 failed:\n%s" % tail

    clocks = re.findall(r"Max frequency for clock\s+'([^']+)':\s+([\d.]+) MHz", log)
    if not clocks:
        return "ok", "placed and routed (no clock frequency reported)"
    report = ", ".join("%s %.1f MHz" % (name, float(mhz)) for name, mhz in clocks)
    return "ok", "placed and routed: %s" % report


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
    totals = {bucket: 0 for bucket in CELL_BUCKETS}
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
    print("Target: %s  (%s, %s)\n"
          % (device.get("part_number"), device.get("family"),
             device.get("package")))

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
        ok, log, json_path = run_yosys(bench, build)
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
                "generic cells survived ECP5 mapping: %s. yosys could not map "
                "this to the fabric -- usually an unsupported construct, a "
                "memory it could not infer into an EBR, or a primitive this "
                "part does not have."
                % ", ".join("%s x%d" % kv for kv in sorted(leftovers.items()))
            )

        totals = roll_up(cells)
        problems.extend(check_budget(bench, totals))

        used = "  ".join("%s %d" % (BUCKET_LABEL[b], totals[b]) for b in
                         ("luts", "ff", "block_ram_blocks", "dsp_mult_18x18"))
        place_note = ""
        if bench.synth["place"]:
            state, message = run_nextpnr(bench, build, json_path, target)
            place_note = message
            if state == "fail":
                problems.append(message)

        rows.append((bench, totals, place_note))
        if problems:
            failures.append((bench, "\n".join(problems)))
            print("[FAIL] %s/%s  %s" % (bench.module, bench.name, used))
        else:
            print("[ok  ] %s/%s  %s%s"
                  % (bench.module, bench.name, used,
                     ("  | " + place_note) if place_note else ""))

    ceiling_problems, declared = ([], {})
    if not args.skip_ceiling and not (args.module or args.only):
        ceiling_problems, declared = check_ceiling(all_benches, target)

    summary = ["| Module | LUTs | FFs | EBRs | DSPs | Budget LUTs | P&R |",
               "|---|---:|---:|---:|---:|---:|---|"]
    for bench, totals, place_note in rows:
        summary.append("| `%s/%s` | %d | %d | %d | %d | %s | %s |" % (
            bench.module, bench.name, totals["luts"], totals["ff"],
            totals["block_ram_blocks"], totals["dsp_mult_18x18"],
            bench.synth["budget"].get("luts", "-"), place_note or "-"))
    if declared:
        resources = target.get("resources", {})
        summary.append("| **declared budgets total** | %d | %d | %d | %d | of %s | |"
                       % (declared["luts"], declared["ff"],
                          declared["block_ram_blocks"], declared["dsp_mult_18x18"],
                          resources.get("luts", "?")))
    table = "\n".join(summary) + "\n"

    out_dir = REPO_ROOT / "build" / "synth"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.md").write_text(table, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("## ECP5 synthesis (%s)\n\n%s\n"
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
