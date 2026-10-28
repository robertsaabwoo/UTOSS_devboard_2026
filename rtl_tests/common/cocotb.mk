# Shared cocotb include.
#
# You should not need to read or edit this. scripts/run_rtl_tests.py passes
# every variable on the make command line (which outranks anything set here or
# in the environment), so this file exists only because cocotb's flow is
# Makefile-based.
#
# Running a single bench by hand, bypassing the runner:
#   cd rtl_tests/examples/reg_handshake
#   make -f ../../common/cocotb.mk \
#        TOPLEVEL=reg_handshake MODULE=test_reg_handshake WAVES=1 \
#        VERILOG_SOURCES="$(git rev-parse --show-toplevel)/rtl/examples/reg_handshake.v"
SIM ?= icarus
TOPLEVEL_LANG ?= verilog

# Waveforms: `make waves` / `dev sim --waves` sets WAVES=1. For Icarus, cocotb
# dumps by compiling in a generated module that calls $dumpfile, writing
# $(SIM_BUILD)/$(TOPLEVEL).fst. It adds that module with a plain `+=` to
# VERILOG_SOURCES and COMPILE_ARGS, but the runner passes both on the make
# command line, which silently overrides any plain `+=`, so no waveform was
# ever written. `override` is what gets through. Moving them into the
# environment instead does not work: cocotb re-invokes make, and the inner
# make appends a second time ("cocotb_iverilog_dump already declared"). A
# command-line value reaches the inner make unappended, so this adds it exactly
# once per level. The file itself, and the -fst plusarg, still come from
# cocotb's Makefile.icarus.
#
# scripts/run_rtl_tests.py fails a bench that was asked for waves and wrote
# none, and CI runs that check, so if a cocotb upgrade changes this, CI goes
# red rather than going quiet.
ifeq ($(WAVES),1)
    ifeq ($(SIM),icarus)
        override VERILOG_SOURCES += $(SIM_BUILD)/cocotb_iverilog_dump.v
        override COMPILE_ARGS += -s cocotb_iverilog_dump
    endif
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
