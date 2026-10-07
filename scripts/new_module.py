#!/usr/bin/env python3
"""Scaffold a new RTL module and its bench so it is already wired into CI.

    python3 scripts/new_module.py fpga dcmi_rx
    tools/dev new fpga dcmi_rx            # same thing, inside the container

Creates:
    rtl/<module>/<name>.v                  module skeleton
    rtl_tests/<module>/<name>/bench.yaml   manifest -- this is what CI discovers
    rtl_tests/<module>/<name>/test_<name>.py

Then `tools/dev all` already runs it. There is no CI file to edit and nothing
to register: the runner discovers any directory containing a bench.yaml.

What is generated passes lint, simulation and the synthesis gate immediately,
on purpose. A scaffold that starts red teaches people to ignore red.
"""
import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

MODULE_TEMPLATE = '''`timescale 1ns / 1ps
`default_nettype none

// {name} -- TODO one line on what this block does.
//
// TODO: link the issue this implements, and the section of rtl/RTL_PLAN.md it
// comes from. A module whose spec lives only in somebody's head is a module
// nobody else can review.
//
// Conventions this file must follow (rtl/README.md has the full list):
//   * one module per file, module name == file name
//   * `default_nettype none above, `default_nettype wire restored at the end
//   * every width parameterized; no bare literals for a bus width
//   * active-low reset, asynchronous assert and synchronous release
//   * no latches, no `initial` blocks for reset state, no blocking assignment
//     in a clocked block
module {name} #(
    // TODO: real parameters. Widths MUST be parameters -- bench.yaml replays
    // this module at several of them, which is how we prove it.
    parameter integer WIDTH = 8
) (
    input  wire                  clk,
    input  wire                  rst_n,

    // TODO: real ports. For a streaming interface use the repo convention
    // (rtl/README.md): <p>_tdata / <p>_tvalid / <p>_tready / <p>_tlast.
    output reg  [WIDTH-1:0]      dummy_out
);

  // SCAFFOLD ONLY -- delete this block with the first real logic. It exists so
  // that the generated module lints clean, maps to real ECP5 cells and passes
  // its bench from the moment it is created.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dummy_out <= {{WIDTH{{1'b0}}}};
    end else begin
      dummy_out <= dummy_out;
    end
  end

endmodule

`default_nettype wire
'''

BENCH_TEMPLATE = '''# Bench manifest for {name}. CI discovers this file -- nothing else to register.
# Field reference: rtl_tests/README.md
name: {name}

# wip while the module is being written: failures are reported loudly but do not
# fail the build on a feature branch. A pull request into main runs --strict,
# where wip is itself a failure -- so flip this to `ready` before you open one.
status: wip

toplevel: {name}
testbench: test_{name}

sources:
  - rtl/{module}/{name}.v

# TODO: widen this sweep as the module grows. Two widths is the minimum that
# proves anything; include the smallest legal width, which is where off-by-one
# slicing bugs live.
param_sets:
  - name: default
    params:
      WIDTH: 8
  - name: narrow
    params:
      WIDTH: 1

timeout_seconds: 120

lint:
  enabled: true
  waivers: []

synth:
  enabled: true
  top: {name}
  param_set: default
  # TODO: set these from the first measured `tools/dev synth` run, then hold the
  # line. The point of a budget is that exceeding it is a decision somebody
  # makes in a pull request, not something that happens quietly.
  budget:
    luts: 256
    ff: 256
    block_ram_blocks: 0
    dsp_mult_18x18: 0
  place: false
'''

TEST_TEMPLATE = '''"""cocotb bench for rtl/{module}/{name}.v.

Read rtl_tests/fpga/reg_handshake/test_reg_handshake.py first -- it is the
worked example, and it shows the three things that matter here: stay
width-generic, assert the failure that would actually hurt, and say in the
assertion message what a failure means for the design.
"""
import cocotb
from cocotb.triggers import RisingEdge

from utoss_tb import assert_param, reset_active_low, start_clock, width_of


@cocotb.test()
async def test_reset_state(dut):
    """Out of reset the module must be in a defined, idle state.

    Keep a test like this even once there are better ones: the payload is
    power-gated, so every imaging pass starts from a cold reset, and anything
    that comes out of reset mid-transaction hangs the supervisor's first
    access.
    """
    start_clock(dut)
    await reset_active_low(dut)

    # Proves the harness: if bench.yaml asked for a width the DUT did not
    # elaborate to, the parameter override never reached the simulator and this
    # parameter set is testing nothing.
    assert_param("WIDTH", width_of(dut.dummy_out))

    assert dut.dummy_out.value == 0, "dummy_out not cleared by reset"


@cocotb.test()
async def test_todo_real_behaviour(dut):
    """TODO: replace with the real checks from the issue's acceptance criteria.

    Delete this test once there is something real to assert. It passes
    trivially, and a bench whose only test passes trivially is worse than no
    bench -- it reports green for an empty module.
    """
    start_clock(dut)
    await reset_active_low(dut)
    await RisingEdge(dut.clk)
'''


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("module", help="module group, e.g. fpga")
    parser.add_argument("name", help="module name, lower_snake_case, e.g. dcmi_rx")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing files")
    args = parser.parse_args()

    for label, value in (("module", args.module), ("name", args.name)):
        if not NAME_RE.match(value):
            print("%s %r must be lower_snake_case starting with a letter. "
                  "Verilog identifiers, file names and the bench directory all "
                  "share this name, so it has to be legal in all three."
                  % (label, value))
            return 1

    rtl_path = REPO_ROOT / "rtl" / args.module / ("%s.v" % args.name)
    bench_dir = REPO_ROOT / "rtl_tests" / args.module / args.name
    bench_path = bench_dir / "bench.yaml"
    test_path = bench_dir / ("test_%s.py" % args.name)

    existing = [p for p in (rtl_path, bench_path, test_path) if p.exists()]
    if existing and not args.force:
        print("refusing to overwrite:")
        for path in existing:
            print("  - %s" % path.relative_to(REPO_ROOT).as_posix())
        print("Pass --force if that is really what you want.")
        return 1

    fields = {"module": args.module, "name": args.name}
    rtl_path.parent.mkdir(parents=True, exist_ok=True)
    bench_dir.mkdir(parents=True, exist_ok=True)
    # newline="\n": these are toolchain files and CI runs on Linux. .gitattributes
    # pins them to LF too, but a file that is CRLF on disk still confuses a
    # local iverilog run on Windows before git ever sees it.
    rtl_path.write_text(MODULE_TEMPLATE.format(**fields), encoding="utf-8",
                        newline="\n")
    bench_path.write_text(BENCH_TEMPLATE.format(**fields), encoding="utf-8",
                          newline="\n")
    test_path.write_text(TEST_TEMPLATE.format(**fields), encoding="utf-8",
                         newline="\n")

    print("created:")
    for path in (rtl_path, bench_path, test_path):
        print("  %s" % path.relative_to(REPO_ROOT).as_posix())
    print("\nNext:")
    print("  tools/dev sim --only %s      # it already runs" % args.name)
    print("  tools/dev lint")
    print("  tools/dev synth --only %s    # set synth.budget from what it reports"
          % args.name)
    print("\nFlip `status: wip` to `ready` in bench.yaml before opening a pull "
          "request into main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
