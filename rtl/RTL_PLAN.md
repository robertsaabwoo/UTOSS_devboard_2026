# FPGA RTL Plan — Hyperspectral Imaging Payload

Scope of Verilog to be written for the ECP5 LFE5U-25F (see `io_specs/fpga.yaml`).
Derived from the UTAT bus/payload team requirements: Camera Link or GigE sensor
interface, 20 MB/s for 1–2 min per day (~1.2–2.4 GB per pass), a couple of GB of
volatile memory, onboard CCSDS compression, SD storage, and an always-on
supervisor CPU that owns configuration and power gating.

`rtl/fpga/reg_handshake.v` is currently the only RTL in the repo. It is a CI
placeholder standing in for item 10 below.

## Data path, in flow order

### 1. Camera receiver — BLOCKED on the interface decision

This block is entirely different depending on the interface chosen, and it
dominates the RTL budget. Nothing downstream of the pixel stream is affected,
so the rest of the list can proceed, but this item cannot start.

- **Camera Link** — LVDS input buffers plus a 7:1 DDR gearbox built from
  `IDDRX` primitives and PLL phase shift. The LFE5U has **no SERDES**, so the
  deserializer is ours to build. Adds per-channel bit alignment and deskew
  training FSM, and Base/Medium/Full word reassembly. Hardest block in the
  project.
- **GigE Vision** — RGMII interface, MAC, UDP/IP, GVSP stream depacketizer,
  GVCP control. Streaming is UDP, so packet reordering and resend handling are
  ours too. Use an existing MAC core; write the GVSP layer.
- **Plain parallel** — PCLK/HSYNC/VSYNC capture, as currently assumed by
  `io_specs/camera.yaml` and the `DCMI_RX` net in `io_specs/fpga.yaml`. Far
  simpler. If the sensor turns out to be a raw module rather than a Camera
  Link/GigE camera, most of this item disappears.

### 2. Frame framer and pixel unpacker

Sync detection, line and frame counters, bit-depth unpacking (10/12/14-bit
packed to aligned words), partial-word handling at line ends. Emits a pixel
stream with frame-valid/line-valid qualifiers.

### 3. Input CDC FIFO

Camera pixel clock to system clock. Async FIFO with gray-code pointers.

Must expose an **overflow counter**. Knowing a cube dropped pixels is far more
useful than silently corrupting a capture that cannot be re-taken.

### 4. Sensor correction — optional but usually needed

Dark-frame subtraction, bad-pixel map, possibly flat-field. Requires a
calibration frame held in BRAM or DDR.

### 5. DDR3 controller and multi-port arbiter

Mandatory — "a couple of gigs of volatile memory" cannot be served by the
ECP5's ~126 KB of block RAM.

**Do not write the PHY.** Use **litedram** (open source, generates Verilog,
well proven on ECP5) or Lattice's IP. What we write around it:

- the multi-port arbiter (camera write port, compressor read and working-set
  ports, storage read port)
- the cube address generator / ring buffer manager

The cube's memory layout — band-interleaved versus line-interleaved — is the
single biggest performance decision in this block, because it determines
whether the compressor's access pattern hits DDR rows efficiently or thrashes
them.

### 6. CCSDS compressor — the actual IP value

- **CCSDS 123.0-B** adaptive predictor (the hyperspectral standard): local
  spatial and spectral neighborhood fetch, weight-update MAC chain (maps to DSP
  blocks), prediction, mapped residual
- **CCSDS 121.0-B** Rice / adaptive entropy coder as the back end, or 123's own
  sample-adaptive encoder
- Code-option search, bit packer/stuffer, header generation

This is where LUT and DSP budget gets tight on a 24k-LUT part.

### 7. Output packer and framing

Variable-length codewords to aligned words, CCSDS Space Packet or TM transfer
frame assembly if standard framing is wanted, CRC.

### 8. Storage writer (SD)

Real architectural lever here. **SPI mode** is roughly 1–5 MB/s and easy;
**4-bit SDIO** is ~20–25 MB/s and substantially more RTL (command/response FSM,
CRC7/CRC16, card-init sequence, tight data timing).

Live 20 MB/s is only required if we write during capture. Buffering the pass in
DDR and offloading afterward puts 2.4 GB at 5 MB/s at about 8 minutes, which is
comfortable against a 1–2 min/day duty cycle. That likely removes the need for
SDIO entirely.

Write **raw blocks plus a simple index**, not FAT32. A filesystem in RTL is
misery; leave it to the supervisor or to ground.

### 9. Camera control UART master

Baud generator, TX/RX, command/response framing, timeouts. Small. Already
specced as `UART_CAM` in `io_specs/fpga.yaml`.

## Control, infrastructure, and glue

### 10. Supervisor register interface

The memory-mapped CSR block that `rtl/fpga/reg_handshake.v` is a placeholder
for. SPI slave is the right choice — STM32 as master, fast, simple. Shift
register, CDC into the system clock, register decode.

Registers: capture start/stop, mode, exposure, compression parameters, status,
frame counts, error and overflow counters, FIFO high-water marks.

### 11. Debug console UART

TX at minimum (`CONSOLE_TX`). A small command parser helps bring-up, but the
supervisor path covers most of it. Ground-support only — see
`io_specs/uart_io.yaml`.

### 12. Clock and reset infrastructure

`EHXPLLL` instances for the system, DDR, and camera domains; per-domain reset
synchronizers; power-on reset.

Because the FPGA is **power-gated** (see the gated rails in
`io_specs/power.yaml`), cold-start sequencing is a genuine design item rather
than boilerplate: configuration load from the supervisor → PLL lock → DDR init
and calibration → ready flag back to the supervisor.

### 13. CDC primitives library

Async FIFO, two-flop synchronizer, pulse-to-handshake crosser. At least four
clock domains are in play (camera pixel, DDR, system, SD). Write these once,
reuse them everywhere, and constrain them properly in the timing script.

### 14. Health, telemetry, SEU

Error counters, overflow flags, heartbeat for the supervisor's watchdog.

The `seu-mitigation` open item in `io_specs/fpga.yaml` lands here: ECP5
configuration SRAM is upset-prone, so configuration readback/CRC with
supervisor-triggered reconfiguration (the supervisor already owns that path per
`io_specs/supervisor.yaml`), plus TMR on critical FSMs.

## Verification

The cocotb gate already exists in CI (`scripts/check_cocotb_results.py`,
`fpga-rtl` job in `.github/workflows/kicad-ci.yml`). Benches worth the effort,
in order of value:

1. **Bit-exact compressor check** — same cube through a software CCSDS 123
   implementation and through the RTL, compare. The most valuable test in the
   project by a wide margin.
2. Camera model driving synthetic frames at real timing, including malformed
   and short frames.
3. Full chain — synthetic cube in, compressed output, software decompress,
   bit-exact match against the input.
4. DDR model (Micron Verilog model, or litedram's sim) and SD card model.

## Risks

**The part may not survive this list.** Rough budget against 24k LUTs: DDR3
controller 3–5k, CCSDS 123 plus Rice coder 5–10k depending on parallelism,
Camera Link RX 2k+, SDIO 2k, infrastructure and CSRs 2k. Plausible, but with
little headroom — and ~126 KB of BRAM is thin for a predictor that needs a line
buffer across bands.

Price the **LFE5U-45F** now, and confirm pin compatibility in the chosen
package **before the PCB is routed**. Discovering this after layout is
expensive.

**Items 1, 5, and 6 are roughly 80% of the work.** Item 1 is blocked on the
camera decision, and item 6 is the only part nobody else has already written.

## Next step

Settle the camera interface (Camera Link vs GigE vs plain parallel), then
scaffold module skeletons with ports plus cocotb bench stubs under `rtl/fpga/`
so the CI gate has real structure to grow into.
