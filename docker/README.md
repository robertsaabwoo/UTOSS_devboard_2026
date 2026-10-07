# RTL toolchain container

One image, built from distribution packages, used identically by `tools/dev` on
a laptop and by `.github/workflows/rtl-ci.yml` in CI. When a bench fails in CI
and passes locally, the cause is the code — not the toolchain.

## Stages

| Stage | Contains | Size | Used for |
|---|---|---|---|
| `sim` | iverilog 12, verilator 5.020, Python 3.12, cocotb 1.9.2 | ~500 MB | lint and simulation |
| `synth` | `sim` + yosys 0.33 + nextpnr-ecp5 0.6 | ~1.0 GB | ECP5 mapping, resource budgets, place-and-route |

`tools/dev` builds `synth` by default so one image covers everything. Build only
`sim` — about half the size, and all you need for the edit/test loop — with:

```bash
UTOSS_RTL_TARGET=sim UTOSS_RTL_IMAGE=utoss-rtl:sim tools/dev build
UTOSS_RTL_TARGET=sim UTOSS_RTL_IMAGE=utoss-rtl:sim tools/dev sim
```

## Building

```bash
tools/dev build          # or: make image
tools/dev rebuild        # discard the image and build from scratch
tools/dev versions       # print what is actually installed
```

Directly:

```bash
docker build -f docker/Dockerfile --target synth -t utoss-rtl:synth .
```

## Why apt packages and not oss-cad-suite

Building yosys and nextpnr from source, or pulling the oss-cad-suite tarball,
multiplies both the image size and the number of ways the image can stop
building. Ubuntu 24.04's packages pin us to one set of versions that every
contributor and CI resolve identically for the life of the release, which is the
property that actually matters here. The cost is older tools: yosys 0.33 rather
than current. If a specific ECP5 fix in a newer yosys turns out to matter, that
is the moment to reconsider — not before.

The one thing pinned by hand is cocotb (`requirements.txt`), to the patch level.
A cocotb minor bump has changed trigger scheduling semantics before, which
silently changes what a bench observes on the edge after a clock edge — and a
bench that silently observes the wrong thing still reports green.

## Networks that re-sign HTTPS

Some campus and corporate networks intercept TLS, which makes `pip` reject
pypi.org with `CERTIFICATE_VERIFY_FAILED` even though the `apt` steps succeeded.
Opt out of verification for that one step:

```bash
UTOSS_PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org" tools/dev build
```

It is off by default and never used in CI — shipping a build that skips
certificate verification to a whole team is a bad default, even when it is
convenient.

## If nextpnr is missing

The `nextpnr-ecp5` install is deliberately non-fatal: on a distribution where
its packaging is broken the image still builds, and `scripts/run_synth_check.py`
reports place-and-route as skipped rather than failing. yosys is **not**
optional — the per-module mapping and resource gate depends on it.
