# UTOSS devboard RTL toolchain.
#
# Two stages so the image most people run in their edit/test loop stays small:
#
#   sim    iverilog + verilator + cocotb.  Lint and simulation only.
#   synth  sim + yosys + nextpnr-ecp5.     ECP5 mapping and P&R gate.
#
# Build the one you need:
#   docker build -f docker/Dockerfile --target sim   -t utoss-rtl:sim   .
#   docker build -f docker/Dockerfile --target synth -t utoss-rtl:synth .
#
# Everything comes from distribution packages on purpose. Building yosys and
# nextpnr from source, or pulling oss-cad-suite, would multiply both the image
# size and the "it worked last week" failure modes; apt pins us to one set of
# versions that every contributor and CI resolve identically for the life of
# the Ubuntu release.
FROM ubuntu:24.04 AS sim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# iverilog     -- the default cocotb simulator for these benches
# verilator    -- used in --lint-only mode as a static gate; it is much
#                 stricter than iverilog about widths, latches and unused or
#                 undriven signals, which is exactly what we want it for
# build-essential + python3-dev -- cocotb compiles a VPI shim at install time
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        iverilog \
        make \
        python3 \
        python3-dev \
        python3-venv \
        verilator \
    && rm -rf /var/lib/apt/lists/*

# A venv rather than --break-system-packages: Ubuntu 24.04 marks its Python
# externally-managed, and a venv keeps our pins from fighting apt's.
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Escape hatch for TLS-inspecting networks (some campus and corporate networks
# re-sign HTTPS, which makes pip reject pypi.org with CERTIFICATE_VERIFY_FAILED
# even though the apt step above succeeded). Opt in with:
#   docker build --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org" ...
# Empty by default, so a normal build and CI verify certificates as usual.
ARG PIP_TRUSTED_HOST=""
ARG PIP_INDEX_URL=""

# Pinned to patch level: a cocotb minor bump has changed trigger scheduling
# semantics before, which silently changes what a bench observes on the edge
# after a clock edge.
COPY docker/requirements.txt /tmp/requirements.txt
RUN set -eu; \
    args=""; \
    for h in $PIP_TRUSTED_HOST; do args="$args --trusted-host $h"; done; \
    if [ -n "$PIP_INDEX_URL" ]; then args="$args --index-url $PIP_INDEX_URL"; fi; \
    pip install --no-cache-dir $args -r /tmp/requirements.txt; \
    rm /tmp/requirements.txt

WORKDIR /work

# Show what a contributor actually has, so a version mismatch between a laptop
# and CI is one `docker run utoss-rtl:sim utoss-versions` away from obvious.
COPY docker/utoss-versions /usr/local/bin/utoss-versions
RUN chmod +x /usr/local/bin/utoss-versions

CMD ["/bin/bash"]


# --- synthesis stage ----------------------------------------------------------
FROM sim AS synth

# yosys alone is enough for the per-module ECP5 mapping and resource gate:
# `synth_ecp5` maps to real ECP5 cells (TRELLIS_COMB/LUT4, TRELLIS_FF, DP16KD,
# MULT18X18D), so LUT/FF/BRAM/DSP counts are honest without placing anything.
# yosys is NOT optional.
RUN apt-get update && apt-get install -y --no-install-recommends yosys \
    && rm -rf /var/lib/apt/lists/*

# nextpnr-ecp5 carries the prjtrellis chip database (~100 MB, the bulk of this
# stage). It is only needed for place-and-route and real timing closure, which
# we run on the top level rather than per module. Its own layer with a
# non-fatal fallback: on a distribution where the nextpnr packaging is missing
# or broken the image still builds, and scripts/run_synth_check.py detects the
# absence and reports P&R as skipped rather than failing.
RUN apt-get update \
    && { apt-get install -y --no-install-recommends nextpnr-ecp5 \
         || echo 'WARNING: nextpnr-ecp5 unavailable; place-and-route checks will skip'; } \
    && rm -rf /var/lib/apt/lists/*

CMD ["/bin/bash"]
