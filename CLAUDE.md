# KnobKraft Orm — Claude Code Guide

## Project Overview

KnobKraft Orm is a free, cross-platform MIDI SysEx librarian written in C++. It stores and organises patches from synthesizers and guitar synths. The main application logic lives in C++ submodules; support for individual synthesizers is added via **Python adaptation files** loaded at runtime.

## Repository Layout

```
adaptations/         Python adaptation files (one .py per synth)
adaptations/tests/   Adaptation unit tests (pytest)
cmake/               CMake helper modules
tests/               C++ unit tests
gr50_tool.py         Standalone GR-50 dump utility (see below)
gr50_params.py       GR-50 parameter definitions (read-only reference)
gr50_params.json     GR-50 parameter JSON export
CMakeLists.txt       Top-level CMake build
```

## Adaptation Development

Each synthesizer is described by a single Python file in `adaptations/`. The file must implement a fixed set of functions; see:

- `adaptations/Adaptation Programming Guide.md` — full API reference
- `adaptations/Adaptation Testing Guide.md` — how to write pytest-based tests

Key API functions every adaptation needs:

| Function | Purpose |
|---|---|
| `name()` | Unique device name (never change after data is saved) |
| `bankDescriptors()` | List of banks; each entry has `bank`, `name`, `size`, `type` |
| `createDeviceDetectMessage(channel)` | SysEx to trigger a device response |
| `channelIfValidDeviceResponse(message)` | Return MIDI channel or -1 |
| `createEditBufferRequest(channel)` | Request the current edit buffer |
| `isEditBufferDump(messages)` | Recognise an edit buffer response |
| `createProgramDumpRequest(channel, patchNo)` | Request a specific program |
| `isSingleProgramDump(messages)` | Recognise a program dump response |
| `convertToEditBuffer(channel, messages)` | Readdress a dump as an edit buffer |
| `convertToProgramDump(channel, messages, program_number)` | Readdress to a memory slot |
| `numberFromDump(messages)` | Extract program number from a dump |
| `nameFromDump(messages)` | Extract patch name |
| `renamePatch(messages, new_name)` | Return dump with new name |
| `calculateFingerprint(messages)` | Stable hash for dedup |

`generalMessageDelay()` returns inter-request pause in ms (GR-50 uses 100).

Multi-bank adaptations: return multiple entries from `bankDescriptors()`. Programs in later banks are offset by the cumulative size of earlier banks (see `Roland_MKS70*.py` as a reference pattern).

## Running Tests

```bash
cd adaptations
pytest                  # run all adaptation tests
pytest test_Roland_GR50.py  # run one adaptation's tests
```

Python deps are in `requirements.txt`; use the `venv/` virtual environment.

## Build System

```bash
cmake -B build .
cmake --build build
```

The `cmake/` directory contains helper modules (e.g. `embed_python_macos.cmake` for bundling the Python interpreter on macOS).

## Roland GR-50

The GR-50 adaptation lives in three files:

| File | Role |
|---|---|
| `adaptations/Roland_GR50.py` | KnobKraft adaptation (two banks) |
| `gr50_params.py` | Parameter layout, address map (read-only reference) |
| `gr50_tool.py` | Standalone MIDI dump utility |

### Protocol

Roland Exclusive Format Type IV: `F0 41 <dev_id> 16 <cmd> <addr[3]> <data…> <checksum> F7`

- Checksum = `(-sum(address + data)) & 0x7F`
- Address space is 7-bit per byte: `flat = a[0]<<14 | a[1]<<7 | a[2]`
- RQ1 (0x11) → one-way request; DT1 (0x12) → one-way data-set
- Device ID = Unit# − 1; Unit 1 → `0x10`

### Key Constants

| Constant | Value | Notes |
|---|---|---|
| `PATCH_SIZE` | 188 | bytes per internal patch |
| `PATCH_COUNT` | 64 | |
| `PATCH_MEMORY_BASE` | `[0x51, 0x00, 0x00]` | |
| `TONE_SIZE` | 246 | bytes of actual tone data |
| `TONE_STRIDE` | **256** | slot size; 246 data + 10 padding |
| `TONE_COUNT` | 64 | |
| `TONE_MEMORY_BASE` | `[0x08, 0x00, 0x00]` | tone[n] at base + n×256 |
| `generalMessageDelay` | 100 ms | inter-request pause |
| `MAX_PAYLOAD` | 64 | bytes per RQ1 chunk in gr50_tool |

> **Critical**: `TONE_STRIDE` must be **256**, not 246. The GR-50 places each user tone at a 256-byte boundary. Using 246 puts requests at invalid addresses and causes timeouts starting at `tones[1]`.

### gr50_tool.py Usage

```bash
python gr50_tool.py dump --port "Your MIDI Port"     # dump all regions
python gr50_tool.py show --dump gr50_dump.gr50       # print summary offline
```

`gr50_dump.gr50` is a generated file — **do not commit it**.

### Bank Layout in Roland_GR50.py

- **Bank 0 — Internal Patches** (programs 0–63): 188 bytes each at `[0x51, …]`
- **Bank 1 — User Tones** (programs 64–127): 246 bytes each at `[0x08, …]`, stride 256

Preset tones (ROM groups a/b) and card patches are not accessible via RQ1.

## Commit Policy

- Do **not** commit `gr50_dump.gr50` or other generated dump files.
- Do **not** push to the remote without explicit confirmation.
