# RTL work breakdown

The specification for every piece of RTL to be written, one file per issue. These
are files first and GitHub issues second: the specification belongs in the
repository, next to the code, where it is reviewable in a pull request and still
readable in two years.

Push them to GitHub with:

```bash
python3 scripts/sync_issues.py --labels --apply   # create the labels first
python3 scripts/sync_issues.py                    # dry run: what would be created
python3 scripts/sync_issues.py --apply            # create the missing issues
```

Matching is by exact title (including the `[ID]` prefix) across open and closed
issues, so re-running is safe. Bodies are only overwritten with `--update-bodies`.

Editing an issue? **Edit the file and re-run the sync.** An issue edited only on
GitHub drifts from the repository, and the repository is what a new contributor
reads.

---

## Where to start

| If you are | Start with |
|---|---|
| New to the project, writing Verilog | `I-01` — the CDC and FIFO primitives. Everything depends on them and they teach the conventions and the test flow. |
| Happier in Python than Verilog | `V-01` (the CCSDS golden model) or `V-02` (the camera model). Both are unblocked and both unblock several RTL issues. |
| Looking for the highest-leverage thing open right now | `V-01`. It is on the critical path for `CMP-01`, `CMP-02`, `CMP-03`, `CMP-04`, `V-03`, `D-04` and `DP-06`, and it is blocked on nothing. |
| Able to settle a decision | `D-01` (camera interface), `D-02` (45F reconciliation), `D-05` (CSR map). All three block RTL. |

Read [`../../rtl/README.md`](../../rtl/README.md) before writing any module, and
[`../../rtl_tests/README.md`](../../rtl_tests/README.md) before writing any bench.
`tools/dev new fpga <name>` scaffolds a module and a bench that already run in CI.

---

## The issues

### Decisions — these block other work

| ID | Title | Blocks |
|---|---|---|
| `D-01` | Camera interface: Camera Link vs GigE vs parallel | `DP-02`, `DP-03`, `C-03`, the pinout |
| `D-02` | Retarget on LFE5U-45F; reconcile io_specs with the RTL target | every resource budget, `I-03` |
| `D-03` | Cube memory layout in DDR3 | `MEM-03`, `CMP-01` |
| `D-04` | SD interface: SPI vs SDIO, and the offload timing budget | `ST-01`, `ST-02` |
| `D-05` | Freeze the CSR map as a machine-readable contract | `C-01`, supervisor firmware |

### Infrastructure

| ID | Title |
|---|---|
| `I-01` | CDC and FIFO primitive library |
| `I-02` | Clock/reset infrastructure and cold-start sequencer |
| `I-03` | Pin constraints, CDC timing exceptions, top-level P&R gate |

### Control

| ID | Title |
|---|---|
| `C-01` | SPI slave + CSR block (replaces the `reg_handshake` placeholder) |
| `C-02` | Parameterized UART core |
| `C-03` | Camera control UART master |
| `C-04` | Debug console UART |
| `C-05` | Health, telemetry and SEU mitigation |

### Datapath

| ID | Title |
|---|---|
| `DP-01` | Parallel camera receiver (DCMI-style) |
| `DP-02` | Camera Link 7:1 deserializer — **blocked on `D-01`** |
| `DP-03` | GigE Vision receiver — **blocked on `D-01`** |
| `DP-04` | Frame framer and pixel unpacker |
| `DP-05` | Input CDC FIFO with overflow telemetry |
| `DP-06` | Sensor correction |

### Memory

| ID | Title |
|---|---|
| `MEM-01` | DDR3 controller integration (litedram) — **do not write the PHY** |
| `MEM-02` | Multi-port DDR3 arbiter |
| `MEM-03` | Cube address generator and ring-buffer manager |

### Compression — the actual IP value

| ID | Title |
|---|---|
| `CMP-01` | CCSDS 123.0-B adaptive predictor |
| `CMP-02` | CCSDS 121.0-B / sample-adaptive entropy coder |
| `CMP-03` | Bit packer / stuffer |
| `CMP-04` | CCSDS Space Packet / TM frame assembly and CRC |

### Storage

| ID | Title |
|---|---|
| `ST-01` | SD writer in SPI mode, raw blocks plus an index |
| `ST-02` | 4-bit SDIO upgrade — **blocked on `D-04`** |

### Integration

| ID | Title |
|---|---|
| `INT-01` | `payload_top`, capture FSM, and the FSM diagram set |

### Verification

| ID | Title |
|---|---|
| `V-01` | CCSDS 123 golden software model and bit-exact harness |
| `V-02` | Camera model BFM with fault injection |
| `V-03` | Full-chain bit-exact round trip |
| `V-04` | DDR3 and SD card simulation models |

---

## Rough critical path

```
V-01 ──────────────────────────────> CMP-01 ─> CMP-02 ─> CMP-03 ─> CMP-04 ─┐
                                        ^                                   │
D-03 ──> MEM-03 ───────────────────────-┘                                   │
          ^                                                                 │
I-01 ─> I-02 ─> MEM-01 ─> MEM-02 ──────-┘                                   ├─> INT-01 ─> V-03
  │                                                                         │
  ├─> D-05 ─> C-01 ────────────────────────────────────────────────────────-┤
  │                                                                         │
  └─> DP-01 ─> DP-04 ─> DP-05 ──────────────────────────────────────────────┤
       ^                                                                    │
D-01 ──┘                                             D-04 ─> ST-01 ────────-┘
```

`V-01`, `V-02`, `I-01`, `D-01`, `D-02`, `D-03`, `D-05` are all unblocked and can
start in parallel today. `CMP-01` and `MEM-*` are roughly 80 % of the remaining
work after that (`rtl/RTL_PLAN.md` "Risks").

---

## Issue file format

```markdown
---
id: I-01
title: "RTL: short description without the ID prefix"
labels: [rtl, P0, "area:infrastructure", "size:M"]
depends_on: [D-02]
milestone: "optional"
---

Markdown body.
```

`id` and `title` are required. The sync script renders `depends_on` into the issue
body as readable references, warns about a dependency no file declares, and refuses
duplicate ids.
