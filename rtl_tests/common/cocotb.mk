# Shared cocotb include.
#
# You should not need to read or edit this. scripts/run_rtl_tests.py passes
# every variable on the make command line (which outranks anything set here or
# in the environment), so this file exists only because cocotb's flow is
# Makefile-based.
#
# Running a single bench by hand, bypassing the runner:
#   cd rtl_tests/examples/reg_handshake
#   VERILOG_SOURCES="$(git rev-parse --show-toplevel)/rtl/examples/reg_handshake.v" \
#   make -f ../../common/cocotb.mk \
#        TOPLEVEL=reg_handshake MODULE=test_reg_handshake WAVES=1
SIM ?= icarus
TOPLEVEL_LANG ?= verilog

# Waveforms: `make waves` / `dev sim --waves` sets WAVES=1, and cocotb's own
# simulator makefile does the rest (for Icarus it compiles in a generated
# $dumpfile module and writes $(SIM_BUILD)/$(TOPLEVEL).fst). That only works
# because the runner passes VERILOG_SOURCES and COMPILE_ARGS through the
# environment: cocotb appends to both, and a command-line value would
# override the append. When running by hand, pass WAVES=1 but set those two
# as environment variables, not as make arguments.

include $(shell cocotb-config --makefiles)/Makefile.sim
