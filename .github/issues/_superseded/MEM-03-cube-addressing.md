---
id: MEM-03
title: "RTL: cube address generator and ring-buffer manager"
labels: [rtl, P0, "area:memory", "size:M"]
depends_on: [MEM-02, D-03, DP-05]
---

## What

The block that turns `(x, y, band)` into a DDR3 address according to the layout
chosen in `D-03`, and manages the cube buffer as a ring so a capture longer than
memory degrades predictably instead of wrapping into itself.

## Why it is its own module

`D-03` decides the layout; this implements it, in **one place**. The camera write
path, the compressor's neighbourhood fetch, the calibration read and the storage
offload all need to agree on where sample `(x, y, band)` lives. Four independent
address calculations is four chances to disagree, and the symptom is a cube that
decompresses into something that looks almost right.

## Interface

```verilog
module cube_addr_gen #(
    parameter integer ADDR_W   = 28,
    parameter integer COORD_W  = 16,
    parameter integer SAMPLE_W = 16,
    parameter integer DATA_W   = 128,
    // 0 = BIL, 1 = BIP, 2 = BSQ. Set by D-03; keep all three implementable so
    // the decision can be re-measured rather than re-written.
    parameter integer LAYOUT   = 0
) (
    input  wire                clk_sys,
    input  wire                rst_sys_n,

    // Geometry, latched at capture start (see requirement 4)
    input  wire [COORD_W-1:0]  cfg_width,
    input  wire [COORD_W-1:0]  cfg_bands,
    input  wire [COORD_W-1:0]  cfg_lines,
    input  wire [ADDR_W-1:0]   cfg_base,
    input  wire [ADDR_W-1:0]   cfg_size,        // ring size in bytes
    input  wire                capture_start,

    // Coordinate to address
    input  wire [COORD_W-1:0]  q_x,
    input  wire [COORD_W-1:0]  q_y,
    input  wire [COORD_W-1:0]  q_band,
    input  wire                q_valid,
    output wire [ADDR_W-1:0]   q_addr,
    output wire [$clog2(DATA_W/8)-1:0] q_byte_off,
    output wire                q_out_of_range,  // see requirement 3
    output wire                q_ready,

    // Ring management
    output wire [ADDR_W-1:0]   write_ptr,
    output wire [ADDR_W-1:0]   read_ptr,
    input  wire [ADDR_W-1:0]   read_ptr_adv,
    output wire                ring_full,
    output wire [15:0]         wrap_count,      // saturating
    output wire [15:0]         err_overwrite    // see requirement 2
);
```

## Behaviour requirements

1. **`LAYOUT` implements the mapping `D-03` chose.** Keep all three layouts
   implementable behind the parameter: `D-03`'s conclusion rests on a bandwidth model,
   and if the measured numbers from `MEM-01` and `MEM-02` disagree with the model, the
   ability to re-measure with a parameter change rather than a rewrite is worth the
   extra code.
2. **Overwriting unread data is an error, not a wrap.** If the write pointer catches
   the read pointer, the choice is: stall the camera (which loses pixels at `DP-05`
   instead, but *countably*), or overwrite (which silently corrupts a cube already in
   the buffer). Pick one, document it, and count it — `err_overwrite`. Silently
   overwriting a partially-compressed cube is the worst outcome available and it is
   the default behaviour of a naive ring buffer.
3. **Out-of-range coordinates produce `q_out_of_range`, never a wrapped address.**
   An address computation that silently wraps on a bad coordinate writes a sample on
   top of unrelated data, and the corruption appears somewhere with no connection to
   the bug. This is the single most valuable assertion in the module.
4. **Geometry is latched at `capture_start` and immutable for the capture.** A
   mid-capture geometry change means the first half of the cube is addressed
   differently from the second, and nothing downstream can detect it.
5. **Avoid a general multiplier if the DSPs are needed elsewhere.** The address
   calculation is a multiply-accumulate over the geometry; if it is walked
   incrementally (the common case — consecutive samples), it reduces to an add per
   sample plus a stride reload at each boundary. `CMP-01` wants the DSP blocks for the
   weight-update chain and has first claim. Implement the incremental path for
   sequential access and the full calculation only for random queries.
6. **Sub-word packing**: at `SAMPLE_W=16` and `DATA_W=128`, eight samples share a
   DDR word. Read-modify-write for a partial word is expensive, so the write path
   should accumulate a full word before issuing. Handle the partial word at the end of
   a line or cube explicitly — this is the same class of bug as `DP-04` requirement 3,
   and it corrupts the first sample of every line.
7. `wrap_count` tells the ground team the capture was longer than the buffer. That
   is important context for interpreting the product.

## Resource budget

Expect 300–600 LUTs and 400 FFs for the incremental path. If a full multiplier is
used, account for the DSP in the budget and justify it against `CMP-01`'s claim. Set
`synth.budget` from a measured run.

## Acceptance criteria

- **Reference model** in Python computing the address for every `(x, y, band)` under
  each `LAYOUT`. Sweep the entire coordinate space for a small geometry and compare
  every address. Exhaustive, not sampled — the bugs here are at boundaries.
- Several geometries including awkward ones: `width` not a multiple of the samples
  per DDR word, `bands = 1`, `bands` prime, `width = 1`.
- **Out-of-range**: `q_x >= cfg_width`, `q_y >= cfg_lines`, `q_band >= cfg_bands`,
  and all three at once — `q_out_of_range` asserts and **no address is emitted**.
- **Ring wrap**: write past `cfg_size`, assert the pointer wraps to `cfg_base`
  exactly and `wrap_count` increments.
- **Write pointer catching the read pointer**: the documented policy happens,
  `err_overwrite` increments, and the bench asserts the policy rather than just the
  counter.
- **Sequential-walk equivalence**: walking the cube in the natural capture order
  through the incremental path produces exactly the same addresses as the full
  calculation for every sample. This is the test that catches requirement 5 going
  wrong, and it is easy to get wrong at line and band boundaries.
- **Partial word at line end**: the first sample of the next line lands at the right
  address and no sample is lost or duplicated.
- Geometry changed mid-capture: the latched values are used and the change is
  reported.
- Address uniqueness: no two distinct in-range coordinates map to the same address
  for any tested geometry. Assert it over the full sweep.

## References

- `rtl/RTL_PLAN.md` §5
- `D-03` (`docs/MEMORY_LAYOUT.md`)
- `MEM-02` (port this attaches to), `CMP-01` (DSP contention)
