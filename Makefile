# Thin wrapper over tools/dev so `make` does the obvious thing.
#
#   make sim          run every cocotb bench in the container
#   make waves        same, and dump an .fst waveform per bench and param set
#   make lint        verilator lint over all RTL
#   make synth        map to UltraScale+ and check resource budgets
#   make all          lint, sim, synth -- the same three gates CI runs
#   make shell        interactive shell in the container
#   make list         list every discovered bench
#   make image        (re)build the container image
#
# Pass extra arguments through ARGS:
#   make waves ARGS="--only frame_crc"
#   make sim ARGS="--only frame_crc --param-set narrow"
#
# On Windows without Git Bash or WSL, use tools\dev.ps1 instead.
ARGS ?=
DEV  := ./tools/dev

.PHONY: all sim waves lint synth shell list image rebuild versions help

all:
	$(DEV) all $(ARGS)

sim:
	$(DEV) sim $(ARGS)

# Dumps land under build/rtl/<group>/<bench>/<param_set>/sim_build/; the runner
# prints each path. Narrow it with ARGS="--only <bench>" -- dumps are large.
waves:
	$(DEV) sim --waves $(ARGS)

lint:
	$(DEV) lint $(ARGS)

synth:
	$(DEV) synth $(ARGS)

shell:
	$(DEV) shell

list:
	$(DEV) list

image:
	$(DEV) build

rebuild:
	$(DEV) rebuild

versions:
	$(DEV) versions

help:
	$(DEV) --help
