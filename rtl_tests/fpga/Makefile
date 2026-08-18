SIM ?= icarus
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES += $(shell pwd)/../../rtl/fpga/reg_handshake.v
TOPLEVEL = reg_handshake
MODULE = test_reg_handshake

include $(shell cocotb-config --makefiles)/Makefile.sim
