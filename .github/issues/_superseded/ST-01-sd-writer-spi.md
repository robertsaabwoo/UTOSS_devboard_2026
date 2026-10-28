---
id: ST-01
title: "RTL: SD card writer in SPI mode, raw blocks plus a simple index"
labels: [rtl, P1, "area:storage", "size:L"]
depends_on: [D-04, CMP-04, I-01]
---

## What

Write the framed product to an SD card over SPI: card initialisation, block writes,
and a simple index so the supervisor or the ground can find a capture.

## Two decisions already made for you

**SPI mode, not SDIO.** Per `D-04` and `rtl/RTL_PLAN.md` §8: buffering the pass in
DDR and offloading afterwards puts 2.4 GB at 5 MB/s at about 8 minutes, which is
comfortable against a 1–2 min/day duty cycle. SPI is roughly 1–5 MB/s and vastly
less RTL than 4-bit SDIO. If `D-04` concluded otherwise, this issue changes and
`ST-02` applies.

**Raw blocks plus an index, not FAT32.** Also from §8: *"A filesystem in RTL is
misery; leave it to the supervisor or to ground."* This is firm. A FAT32
implementation in Verilog is a large amount of code whose failure mode is an
unreadable card.

## Deliverables

- `rtl/fpga/sd_spi_phy.v` — SPI bit-level interface with the SD clock-rate switch
- `rtl/fpga/sd_init_fsm.v` — card initialisation and identification
- `rtl/fpga/sd_writer.v` — block write path plus the index
- `rtl/fpga/crc7.v`, `rtl/fpga/crc16.v`
- `rtl_tests/common/stubs/sd_card_model.v` or a cocotb SD model — **write this
  first**, see below
- `docs/FSM_SD.md` — the state diagram (the client asked for FSM diagrams)
- `docs/CARD_LAYOUT.md` — the on-card format, for the supervisor and the ground tools

## Write the card model first

A card initialisation FSM cannot be verified without a model that answers like a
card, including answering **badly**. Build the model before the FSM: it needs to be
able to reject a command, return a bad CRC, go busy for a long time, report a write
error, and refuse to initialise at all. Without those, the bench can only test the
path that works, which is the path that never causes a problem on orbit.

## Interface

```verilog
module sd_writer #(
    parameter integer DATA_W      = 32,
    parameter integer BLOCK_BYTES = 512,
    // 400 kHz during init, then full rate. Both derived from clk_sd.
    parameter integer INIT_DIV    = 125,
    parameter integer RUN_DIV     = 2,
    parameter integer WRITE_TIMEOUT_CYCLES = 10_000_000,
    parameter integer RETRIES     = 3
) (
    input  wire               clk_sd,
    input  wire               rst_sd_n,

    // SD pins (SPI mode)
    output wire               sd_clk,
    output wire               sd_cs_n,
    output wire               sd_mosi,
    input  wire               sd_miso,

    // Control, from the CSR
    input  wire               start_offload,
    input  wire [31:0]        start_block,
    output wire               busy,
    output wire               done,

    // Data in, from CMP-04 (via a CDC FIFO if clk_sd != clk_sys)
    input  wire [DATA_W-1:0]  d_tdata,
    input  wire               d_tvalid,
    input  wire               d_tlast,
    output wire               d_tready,

    // Status / telemetry, all saturating
    output wire [7:0]         card_type,        // SDSC / SDHC / SDXC / none
    output wire [31:0]        blocks_written,
    output wire [15:0]        err_init,
    output wire [15:0]        err_crc,
    output wire [15:0]        err_timeout,
    output wire [15:0]        err_write,
    output wire [15:0]        max_busy_cycles,  // see requirement 4
    output wire [7:0]         fail_code
);
```

## Behaviour requirements

1. **The initialisation sequence is exact and unforgiving**: CMD0, CMD8, ACMD41 with
   the HCS bit, CMD58, CMD16 if needed, with the correct clock rate (≤400 kHz) and the
   correct dummy clocks before and after `cs_n` transitions. Follow the SD Physical
   Layer Simplified Specification, not a blog post. Each step gets a distinct
   `fail_code` — "the card did not initialise" is not actionable, and on a power-gated
   payload this runs on every wake-up.
2. **SDHC addresses blocks, SDSC addresses bytes.** Detect the card type and address
   accordingly. Getting this wrong writes to an address 512 times off and corrupts the
   card. Report `card_type` so the supervisor can sanity-check it.
3. **Every wait has a timeout**, and a timeout is a counted error, never an infinite
   wait. A storage block stuck waiting for a card that has stopped responding is a
   payload that silently writes nothing for the rest of the mission.
4. **`max_busy_cycles` is important telemetry, not a nicety.** SD cards do internal
   wear levelling and garbage collection at unpredictable moments and can go busy for
   hundreds of milliseconds. Measuring the worst case seen is how we find out whether
   the write path's buffering is adequate before it is not — and it is the number that
   decides whether a consumer card is usable at all.
5. **Retry, then report.** On CRC error or write error: retry up to `RETRIES`, then
   count it and continue to the next block rather than aborting the whole offload. One
   bad block should cost one block, not the capture.
6. **Write the index last.** The index (capture start block, length, timestamp,
   sequence) is written only after the data blocks are confirmed, so a power loss
   mid-offload leaves an index that describes only complete captures. An index written
   first points at data that may not exist, and a ground tool will trust it.
7. **The card layout must be documented and simple enough to read with `dd`.** A
   superblock at a fixed block address with a magic number, format version, and a table
   of captures. The supervisor and ground tools both parse it; it needs to be readable
   without our RTL.
8. **CRC7 (commands) and CRC16 (data)** verified against published vectors, not only
   against themselves.
9. `default:` arm on every FSM; this is a TMR candidate in `C-05`.

## Resource budget

`rtl/RTL_PLAN.md` estimates 2k LUTs for SDIO; SPI mode should be well under that —
budget 600–1000 LUTs and 600 FFs including both CRCs and the init FSM.

## Acceptance criteria

The card model must be able to misbehave, and each of these is a test:

- Full initialisation against a model of each card type; `card_type` correct.
- **Card never responds to CMD0**: `err_init` increments, distinct `fail_code`, no
  deadlock.
- **Card rejects ACMD41 repeatedly** (still initialising): the FSM retries within its
  timeout, then fails with a distinct code.
- **No card present**: detected, reported, no deadlock.
- Block write round trip: write a known pattern, read it back from the model, exact
  match.
- **SDHC vs SDSC addressing**: a test asserting the address sent on the wire for a
  given logical block differs correctly between the two card types. This is
  requirement 2 and it is easy to get wrong in a way that only shows on real hardware.
- **CRC error injected** on a data block: retried, succeeds on retry, `err_crc`
  counts exactly one.
- **Persistent CRC error**: retries exhausted, `err_crc` and `err_write` count, the
  offload continues to the next block.
- **Card busy for a long time** (longer than typical, within the timeout): write
  completes, `max_busy_cycles` records it accurately.
- **Card busy past the timeout**: `err_timeout` increments, recovery happens.
- **Sustained throughput measured** at `RUN_DIV`, reported in the pull request, and
  checked against `D-04`'s required rate. If it does not meet it, that is a finding for
  `D-04`, not something to absorb quietly.
- **Power loss simulation**: stop the offload mid-capture; the index must not
  reference the incomplete capture. Assert this by parsing the model's card contents.
- `docs/CARD_LAYOUT.md` plus a Python tool that reads a card image and lists the
  captures.

## References

- `rtl/RTL_PLAN.md` §8
- `D-04` (mode decision, required rate, card selection)
- SD Physical Layer Simplified Specification
