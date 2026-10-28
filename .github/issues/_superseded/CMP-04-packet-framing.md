---
id: CMP-04
title: "RTL: output framing — CCSDS Space Packet / TM transfer frame assembly and CRC"
labels: [rtl, P1, "area:compression", "size:M"]
depends_on: [CMP-03, D-05]
---

## What

Wrap the packed bitstream in a container the ground segment can parse: a CCSDS
header with the cube's geometry and compression configuration, segmentation into
packets, and a CRC per packet.

## Why framing matters even though the data is going to an SD card first

The product has to be interpretable on the ground by someone who was not in the
room. That needs, at minimum, the cube geometry, the exact CCSDS 123 configuration
(`CMP-01`'s `docs/CCSDS123_CONFIG.md`), the bit count and padding from `CMP-03`, and
a capture timestamp or sequence number. A bare bitstream on an SD card with that
information living in somebody's notebook is not a deliverable.

A CRC per packet also means a cube damaged in storage or downlink is **detected**,
and the damage is localised to one packet rather than silently corrupting the
decompression from that point on.

## Deliverables

- `rtl/fpga/packet_framer.v`
- `rtl/fpga/crc_gen.v` — parameterized CRC (CRC-16-CCITT at minimum)
- A bench for each
- `docs/PRODUCT_FORMAT.md` — the byte-level format, written for the ground segment.
  This is a client-facing document.

## Decide first

- [ ] **Full CCSDS Space Packet / TM transfer frames, or a simpler in-house
      container?** `rtl/RTL_PLAN.md` §7 says "if standard framing is wanted". Standard
      framing is more RTL and buys interoperability with a ground segment that speaks
      CCSDS. Ask the bus team: the meeting notes say the downstream interface can be
      CAN, which means something between us and the radio is already reframing. If so,
      a simple documented container may be the right answer and the CCSDS framing
      belongs downstream.
- [ ] **Packet size.** Smaller packets localise damage better and cost more header
      overhead. Decide against the expected link, not in the abstract.

## Interface

```verilog
module packet_framer #(
    parameter integer IN_W         = 128,
    parameter integer OUT_W        = 32,
    parameter integer MAX_PKT_BYTES = 65536,
    parameter integer APID         = 11'h100
) (
    input  wire                 clk_sys,
    input  wire                 rst_sys_n,

    // Cube metadata, latched at capture start (from the CSR, D-05)
    input  wire                 capture_start,
    input  wire [15:0]          cfg_width,
    input  wire [15:0]          cfg_lines,
    input  wire [15:0]          cfg_bands,
    input  wire [31:0]          cfg_compress_params,
    input  wire [31:0]          cfg_timestamp,
    input  wire [15:0]          cfg_sequence,

    // Packed bitstream in, from CMP-03
    input  wire [IN_W-1:0]      w_tdata,
    input  wire                 w_tvalid,
    input  wire                 w_tlast,
    output wire                 w_tready,
    input  wire [39:0]          total_bits,
    input  wire [6:0]           final_pad_bits,

    // Framed output, to ST-01
    output wire [OUT_W-1:0]     p_tdata,
    output wire                 p_tvalid,
    output wire                 p_tlast,     // last word of a packet
    input  wire                 p_tready,

    output wire [15:0]          packet_count,
    output wire [15:0]          err_metadata  // see requirement 3
);
```

## Behaviour requirements

1. **The header must carry everything needed to decompress**, with no reference to
   anything outside the file: cube geometry, the full CCSDS 123 configuration, bit
   count, padding bits, timestamp, sequence number, and an RTL version identifier. A
   product that can only be decoded by somebody who knows which bitstream produced it
   is not a product.
2. **A format version field in the header.** The format will change at least once; a
   file with no version is a file nobody can safely parse in two years.
3. **Metadata must be present and plausible.** If `cfg_*` are all zero at
   `capture_start` — which is what an unconfigured CSR looks like — increment
   `err_metadata` and refuse to emit a header that claims a 0×0×0 cube. A product
   labelled with wrong geometry is harder to recover from than one with none.
4. **CRC covers the header and the payload of each packet**, and the polynomial, seed
   and bit order are documented in `docs/PRODUCT_FORMAT.md`. Verify the implementation
   against published CRC test vectors, not only against itself — a self-consistent
   wrong CRC passes every test you write and fails on the ground.
5. **The last packet may be short.** Pad it, and record the real length in its
   header. Same reasoning as `CMP-03` requirement 3.
6. Sequence counters per packet, so a missing packet is detectable rather than
   producing a silently shortened cube.
7. Backpressure must not corrupt a packet in flight.

## Resource budget

Expect 400–800 LUTs and 400 FFs, plus a small header buffer. The CRC is cheap. Set
`synth.budget` from a measured run.

## Acceptance criteria

- **Reference model** in Python producing the expected byte stream; compare byte for
  byte.
- **A Python parser for the format**, committed alongside the bench, that reads the
  framed output and recovers geometry, configuration and payload. This parser is what
  the ground segment will actually start from, so writing it here is not extra work —
  it is the deliverable that proves requirement 1.
- CRC verified against published CRC-16-CCITT test vectors.
- Injected single-bit error in a packet payload: the CRC check in the Python parser
  fails on exactly that packet and no other.
- Cube sizes producing exactly one packet, exactly two, and a short final packet.
- Payload that is an exact multiple of the packet size (so the final packet is full,
  not short) — the boundary case that is easy to get wrong in both directions.
- Zero metadata at `capture_start`: `err_metadata` increments, no bogus header.
- Sequence numbers monotonic with no gaps across a multi-packet cube.
- Backpressure and gaps: byte-identical output to the gapless run.
- **Full round trip**: RTL output → Python parser → `V-01` decompressor → original
  cube, bit-exact.

## References

- `rtl/RTL_PLAN.md` §7
- CCSDS 133.0-B (Space Packet Protocol), CCSDS 132.0-B (TM Space Data Link)
- `UTAT Meeting.txt`: "Interfacing with the downstream can be done over CAN";
  "L2 data ... want us to perform calculations on the incoming data"
