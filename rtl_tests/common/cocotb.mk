# Shared cocotb include.
#
# You should not need to read or edit this. scripts/run_rtl_tests.py passes
# every variable on the make command line (which outranks anything set here or
# in the environment), so this file exists only because cocotb's flow is
# Makefile-based.
#
# Running a single bench by hand, bypassing the runner:
#   cd rtl_tests/fpga/reg_handshake
#   make -f ../../common/cocotb.mk \
#        TOPLEVEL=reg_handshake MODULE=test_reg_handshake \
#        VERILOG_SOURCES="$(git rev-parse --show-toplevel)/rtl/fpga/reg_handshake.v"
SIM ?= icarus
TOPLEVEL_LANG ?= verilog

# Waveforms: the runner sets WAVES=1 for `dev sim --waves`. Icarus needs the
# dump to be requested at compile time, hence the plusarg rather than a switch.
ifeq ($(WAVES),1)
    ifeq ($(SIM),icarus)
        PLUSARGS += -fst
    endif
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
