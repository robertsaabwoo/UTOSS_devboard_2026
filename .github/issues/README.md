# Work breakdown: Kria K26 plan

One file per issue, following the Drive document *PAY FPGA BOARD Project
Milestones*. These are files first and GitHub issues second: the specification
belongs in the repository, where it is reviewable in a pull request.

Push them to GitHub with:

```bash
python3 scripts/sync_issues.py --labels --milestones --apply   # labels and milestones first
python3 scripts/sync_issues.py                                 # dry run: what would be created
python3 scripts/sync_issues.py --apply                         # create the missing issues
```

Matching is by exact title (including the `[ID]` prefix) across open and closed
issues, so re-running is safe. Bodies are only overwritten with `--update-bodies`.

Editing an issue? **Edit the file and re-run the sync.**

---

## The plan

The board is a carrier for an AMD **Kria K26** SOM (Zynq UltraScale+), developed
first on a **KV260** kit. The ARM cores run Linux and handle the USB 3.0 camera
and storage; the fabric handles the frame path and CCSDS 123 compression.

Each build runs three streams in parallel, which are the `stream:` labels:

| Stream | What |
|---|---|
| **Camera** | ARM side: test data, replay loader, camera library, then the real camera over USB 3.0 |
| **Hardware** | The carrier board: power and peripherals around the SOM |
| **RTL** | Verilog in the FPGA fabric |
| **All** | Shared work |

Dates: design in Fall 2026, **design review January 2027**, fabrication February,
testing through Winter 2027, **final demo May 2027**.

---

## Where to start

| If you are | Start with |
|---|---|
| Anyone, first week | `B1.1`: toolchain installed and a blinky on the KV260 |
| Writing Verilog | `B1.5`: AXI DMA loopback. Every later RTL milestone plugs into it |
| Happier in Python or on Linux | `B1.2` (test data) then `B1.3` (replay loader) |
| On the hardware team | `B1.4`: choose the K26, block diagram, OBC interface |
| Able to talk to UTAT | `B1.2` (confirm camera, rate, interface) and `B1.6` (request the SHyLoC licence now) |

---

## The issues

### Build 1: Foundations

| ID | Stream | Milestone |
|---|---|---|
| `B1.1` | All | Tools installed, repo and tracker set up, blinky on the KV260 |
| `B1.2` | Camera | Test data set and data budget agreed with UTAT |
| `B1.3` | Camera | Replay loader: 2-min pass with zero drops |
| `B1.4` | Hardware | K26 chosen, carrier block diagram, BOM v0, OBC interface v0 |
| `B1.5` | RTL | AXI DMA loopback, 1 GB round trip |
| `B1.6` | RTL | CCSDS 123 groundwork: reference, mapping, licence, SHyLoC vs HLS |
| `B1.7` | All | Build 1 review with UTAT |
| `INF-01` | All | Retarget CI and the repo from the ECP5 to the K26 |

### Build 2: Interfaces proven; custom board designed

| ID | Stream | Milestone |
|---|---|---|
| `B2.1` | Camera | Loader becomes a documented library |
| `B2.2` | Camera | Live pipeline with replayed data through the fabric to storage |
| `B2.3` | Hardware | Breadboard MCU, load switches, SOM power sequence |
| `B2.4` | Hardware | Carrier schematic and review |
| `B2.5` | Hardware | Carrier layout; **January design review**; boards ordered |
| `B2.6` | RTL | AXI-Stream frame path with header and CRC |
| `B2.7` | RTL | CCSDS 123 bit-exact in simulation |

### Build 3: Custom board brought up

| ID | Stream | Milestone |
|---|---|---|
| `B3.1` | Hardware | Bring-up: rails, MCU, Linux, JTAG |
| `B3.2` | Hardware | Each interface tested on its own |
| `B3.3` | Camera | Real camera behind the library, 2-min live pass |
| `B3.4` | RTL | CCSDS 123 in the fabric, bit-exact on 10 passes |
| `B3.5` | All | Power measured, errata collected |

### Build 4: End-to-end and final demo

| ID | Stream | Milestone |
|---|---|---|
| `B4.1` | Hardware | Rework rev A, repeat bring-up |
| `B4.2` | RTL | CCSDS 123 inline on the carrier with CRC per segment |
| `B4.3` | All | End to end: capture, compress, store, read out over OBC |
| `B4.4` | All | Soak: 10 passes plus a USB cable pull |
| `B4.5` | All | Documentation and final demo to UTAT |

### After Build 4: space-grade PAY board (visibility only)

`A.1` flight parts, `A.2` fault protection, `A.3` form factor, `A.4`
environment, `A.5` EMC, `A.6` timing.

---

## Rough critical path

```
B1.1 -> B1.5 ------------------------------> B2.6 --+
B1.2 -> B1.6 (licence!) -------------------> B2.7 --+--> B3.4 -> B4.2 --+
B1.2 -> B1.3 -> B2.1 -> B2.2                        |                   |
                  +---------------------------> B3.3 --+                +--> B4.3 -> B4.4 -> B4.5
B1.4 -> B2.3 -> B2.4 -> B2.5 (Jan review) -> B3.1 -> B3.2 -> B3.5 -> B4.1 --+
```

The hardware stream holds the only hard date: the January design review, since
fabrication follows in February. The SHyLoC licence request in `B1.6` is the
other long lead; send it in the first weeks.

---

## The superseded ECP5 plan

The earlier breakdown targeted a Lattice ECP5 with a hand-written DDR3
controller, SD writer, camera receivers and CCSDS 123 core. It is kept in
[`_superseded/`](_superseded/) for its specifications, which several new issues
reuse (each new issue names the files it draws on). The sync script ignores that
folder, and the matching GitHub issues are closed as not planned with a pointer
to their replacement.

---

## Issue file format

```markdown
---
id: B1.5
title: "RTL: short description without the ID prefix"
labels: ["stream:rtl", rtl, P0, "size:M"]
milestone: "Build 1: Foundations"
depends_on: [B1.1]
---

Markdown body.
```

`id` and `title` are required. `milestone` must match a title in
`.github/milestones.yml`. The sync script renders `depends_on` into the issue
body as readable references, warns about a dependency no file declares, and
refuses duplicate ids.
