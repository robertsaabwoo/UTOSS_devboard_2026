#!/usr/bin/env python3
"""Discovery and strict validation of rtl_tests/**/bench.yaml manifests.

Shared by run_rtl_tests.py, lint_rtl.py and run_synth_check.py so all three
agree on what a bench is. Validation is strict and names the offending key:
the failure mode we are designing against is a manifest typo that makes a
bench silently not run, which looks exactly like a passing build.
"""
import pathlib
import sys
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced as an actionable message
    sys.exit("PyYAML is required: pip install pyyaml (or run inside the "
             "container -- see docker/README.md)")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "rtl_tests"
TARGET_FILE = REPO_ROOT / "rtl" / "ecp5_target.yaml"

STATUSES = ("ready", "wip", "blocked")

TOP_LEVEL_KEYS = {
    "name", "status", "blocked_reason", "toplevel", "testbench", "sources",
    "param_sets", "timeout_seconds", "simulator", "defines", "lint", "synth",
}
LINT_KEYS = {"enabled", "top", "waivers"}
SYNTH_KEYS = {"enabled", "top", "param_set", "budget", "place", "lpf", "target_mhz"}
BUDGET_KEYS = {"luts", "ff", "block_ram_blocks", "dsp_mult_18x18"}


class BenchError(Exception):
    """A manifest is malformed. The message is written for the contributor."""


class ParamSet:
    def __init__(self, name: str, params: Dict[str, int]):
        self.name = name
        self.params = params

    def __repr__(self):
        return "ParamSet(%r, %r)" % (self.name, self.params)


class Bench:
    def __init__(self, path: pathlib.Path, data: dict):
        self.path = path
        self.dir = path.parent
        self.rel_dir = self.dir.relative_to(REPO_ROOT).as_posix()
        # rtl_tests/<module>/<bench>/ -- the first segment groups benches the
        # way the hardware CI groups schematic modules, so `--module fpga`
        # selects the same set of things in both.
        parts = self.dir.relative_to(BENCH_DIR).parts
        self.module = parts[0] if len(parts) > 1 else "fpga"

        unknown = set(data) - TOP_LEVEL_KEYS
        if unknown:
            raise BenchError(
                "%s/bench.yaml: unknown key(s) %s. Valid keys: %s"
                % (self.rel_dir, sorted(unknown), sorted(TOP_LEVEL_KEYS))
            )

        self.name = data.get("name") or self.dir.name
        self.status = data.get("status", "ready")
        if self.status not in STATUSES:
            raise BenchError(
                "%s/bench.yaml: status=%r is not one of %s"
                % (self.rel_dir, self.status, STATUSES)
            )

        self.blocked_reason = data.get("blocked_reason", "")
        if self.status == "blocked" and not self.blocked_reason:
            raise BenchError(
                "%s/bench.yaml: status: blocked requires blocked_reason -- a "
                "bench that is switched off without a stated reason stays off "
                "forever." % self.rel_dir
            )

        self.toplevel = self._require(data, "toplevel")
        self.testbench = self._require(data, "testbench")
        self.simulator = data.get("simulator", "icarus")
        self.timeout_seconds = int(data.get("timeout_seconds", 300))
        self.defines = data.get("defines") or {}

        tb_file = self.dir / (self.testbench + ".py")
        if self.status != "blocked" and not tb_file.is_file():
            raise BenchError(
                "%s/bench.yaml: testbench=%r but %s does not exist."
                % (self.rel_dir, self.testbench,
                   tb_file.relative_to(REPO_ROOT).as_posix())
            )

        self.sources = self._resolve_sources(data)
        self.param_sets = self._resolve_param_sets(data)
        self.lint = self._resolve_lint(data)
        self.synth = self._resolve_synth(data)

    # -- helpers ---------------------------------------------------------
    def _require(self, data, key):
        value = data.get(key)
        if not value:
            raise BenchError(
                "%s/bench.yaml: missing required key %r" % (self.rel_dir, key)
            )
        return value

    def _resolve_sources(self, data) -> List[pathlib.Path]:
        raw = data.get("sources")
        if not raw:
            raise BenchError(
                "%s/bench.yaml: `sources` must list at least one "
                "repo-relative Verilog file." % self.rel_dir
            )
        if not isinstance(raw, list):
            raise BenchError(
                "%s/bench.yaml: `sources` must be a list" % self.rel_dir
            )

        resolved: List[pathlib.Path] = []
        for entry in raw:
            matches = sorted(REPO_ROOT.glob(entry))
            if not matches:
                if self.status == "blocked":
                    # The DUT legitimately does not exist yet.
                    continue
                raise BenchError(
                    "%s/bench.yaml: source %r matches no file. Paths are "
                    "relative to the repository root, not to the bench "
                    "directory." % (self.rel_dir, entry)
                )
            for match in matches:
                if match not in resolved:
                    resolved.append(match)
        return resolved

    def _resolve_param_sets(self, data) -> List[ParamSet]:
        raw = data.get("param_sets")
        if raw is None:
            return [ParamSet("default", {})]
        if not isinstance(raw, list) or not raw:
            raise BenchError(
                "%s/bench.yaml: `param_sets` must be a non-empty list" % self.rel_dir
            )
        sets, seen = [], set()
        for index, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise BenchError(
                    "%s/bench.yaml: param_sets[%d] must be a mapping with "
                    "`name` and `params`" % (self.rel_dir, index)
                )
            name = entry.get("name") or ("set%d" % index)
            if name in seen:
                raise BenchError(
                    "%s/bench.yaml: duplicate param_set name %r -- the two "
                    "runs would overwrite each other's results"
                    % (self.rel_dir, name)
                )
            seen.add(name)
            params = entry.get("params") or {}
            for key, value in params.items():
                if not isinstance(value, int) or isinstance(value, bool):
                    raise BenchError(
                        "%s/bench.yaml: param_sets[%s].params.%s must be an "
                        "integer (got %r). Only integer parameter overrides "
                        "survive the simulator command line reliably."
                        % (self.rel_dir, name, key, value)
                    )
            sets.append(ParamSet(name, params))
        return sets

    def _resolve_lint(self, data) -> dict:
        lint = data.get("lint") or {}
        unknown = set(lint) - LINT_KEYS
        if unknown:
            raise BenchError(
                "%s/bench.yaml: unknown lint key(s) %s"
                % (self.rel_dir, sorted(unknown))
            )
        return {
            "enabled": lint.get("enabled", True),
            "top": lint.get("top", self.toplevel),
            "waivers": lint.get("waivers") or [],
        }

    def _resolve_synth(self, data) -> dict:
        synth = data.get("synth") or {}
        unknown = set(synth) - SYNTH_KEYS
        if unknown:
            raise BenchError(
                "%s/bench.yaml: unknown synth key(s) %s"
                % (self.rel_dir, sorted(unknown))
            )
        budget = synth.get("budget") or {}
        unknown_budget = set(budget) - BUDGET_KEYS
        if unknown_budget:
            raise BenchError(
                "%s/bench.yaml: unknown synth.budget key(s) %s. Valid: %s"
                % (self.rel_dir, sorted(unknown_budget), sorted(BUDGET_KEYS))
            )
        param_set = synth.get("param_set", self.param_sets[0].name)
        if param_set not in set(ps.name for ps in self.param_sets):
            raise BenchError(
                "%s/bench.yaml: synth.param_set=%r is not one of the declared "
                "param_sets" % (self.rel_dir, param_set)
            )
        return {
            "enabled": synth.get("enabled", True),
            "top": synth.get("top", self.toplevel),
            "param_set": param_set,
            "budget": budget,
            "place": synth.get("place", False),
            "lpf": synth.get("lpf"),
            "target_mhz": synth.get("target_mhz"),
        }

    def param_set(self, name: str) -> Optional[ParamSet]:
        for candidate in self.param_sets:
            if candidate.name == name:
                return candidate
        return None

    def build_dir(self, param_set_name: str) -> pathlib.Path:
        return REPO_ROOT / "build" / "rtl" / self.module / self.name / param_set_name

    def __repr__(self):
        return "Bench(%s/%s, status=%s)" % (self.module, self.name, self.status)


def discover(module: Optional[str] = None,
             only: Optional[str] = None) -> List[Bench]:
    """Find and validate every bench. Raises BenchError on the first bad one.

    Directories whose name starts with `_` are skipped, which is how
    rtl_tests/_template stays out of CI.
    """
    if not BENCH_DIR.is_dir():
        raise BenchError("%s does not exist" % BENCH_DIR)

    benches = []
    for manifest in sorted(BENCH_DIR.rglob("bench.yaml")):
        rel_parts = manifest.relative_to(BENCH_DIR).parts
        if any(part.startswith("_") for part in rel_parts):
            continue
        try:
            data = yaml.safe_load(manifest.read_text()) or {}
        except yaml.YAMLError as exc:
            raise BenchError(
                "%s: invalid YAML: %s"
                % (manifest.relative_to(REPO_ROOT).as_posix(), exc)
            )
        if not isinstance(data, dict):
            raise BenchError(
                "%s: top level must be a mapping"
                % manifest.relative_to(REPO_ROOT).as_posix()
            )
        benches.append(Bench(manifest, data))

    seen = {}
    for bench in benches:
        key = (bench.module, bench.name)
        if key in seen:
            raise BenchError(
                "two benches both named %r under module %r: %s and %s. "
                "Results would overwrite each other."
                % (bench.name, bench.module, seen[key], bench.rel_dir)
            )
        seen[key] = bench.rel_dir

    if module:
        benches = [b for b in benches if b.module == module]
    if only:
        benches = [b for b in benches
                   if b.name == only or b.rel_dir.endswith(only)]
    return benches


def load_target() -> dict:
    """Read rtl/ecp5_target.yaml."""
    if not TARGET_FILE.is_file():
        raise BenchError(
            "%s is missing -- it defines the synthesis target" % TARGET_FILE
        )
    return yaml.safe_load(TARGET_FILE.read_text()) or {}


def main() -> None:
    """`python3 scripts/rtl_bench.py` validates every manifest and lists them."""
    try:
        benches = discover()
    except BenchError as exc:
        print("BENCH MANIFEST ERROR: %s" % exc)
        sys.exit(1)
    if not benches:
        print("No benches found under rtl_tests/.")
        sys.exit(0)
    width = max(len(b.name) for b in benches)
    for bench in benches:
        params = ", ".join(ps.name for ps in bench.param_sets)
        print("%-10s %-*s %-8s [%s]  %s"
              % (bench.module, width, bench.name, bench.status, params,
                 bench.rel_dir))
    print("\n%d bench manifest(s) validated." % len(benches))


if __name__ == "__main__":
    main()
