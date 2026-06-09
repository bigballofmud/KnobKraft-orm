#!/usr/bin/env python3
"""
gr50_tool.py — Roland GR-50 memory dump and card writer

Usage:
  python gr50_tool.py dump   [--port PORT] [--unit N] [--out FILE]
  python gr50_tool.py write  [--port PORT] [--unit N] [--dump FILE] [--bank internal|card]

Commands:
  dump   Read all GR-50 internal memory to a .gr50 file
  write  Write one patch bank from a dump file to a destination (internal or card)

The dump file is a JSON file containing raw SysEx data for each memory region,
plus metadata. The card write path uses the Write Request mechanism so the GR-50
handles card formatting itself (as it does on a brand-new card via the front panel).

Dependencies:
  pip install python-rtmidi
"""

import argparse
import json
import sys
import time
import datetime
import threading
from pathlib import Path

try:
    import rtmidi
except ImportError:
    print("ERROR: python-rtmidi not installed. Run: pip install python-rtmidi")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

ROLAND_ID  = 0x41
MODEL_ID   = 0x16
CMD_RQ1    = 0x11   # one-way request
CMD_DT1    = 0x12   # one-way data
CMD_WSD    = 0x40   # handshake: want to send
CMD_RQD    = 0x41   # handshake: request
CMD_DAT    = 0x42   # handshake: data
CMD_ACK    = 0x43   # handshake: acknowledge
CMD_EOD    = 0x45   # handshake: end of data
CMD_ERR    = 0x4E   # handshake: error
CMD_RJC    = 0x4F   # handshake: rejection

MAX_PAYLOAD = 64    # bytes per RQ1/DT1 chunk; smaller = shorter TX = easier timing
TIMEOUT_S   = 2.0   # seconds to wait for a response

# ---------------------------------------------------------------------------
# 7-bit address arithmetic
# ---------------------------------------------------------------------------

def _flat(addr):
    return addr[0] * 128 * 128 + addr[1] * 128 + addr[2]

def _from_flat(n):
    lsb = n % 128;  n //= 128
    mid = n % 128;  msb = n // 128
    return [msb & 0x7F, mid & 0x7F, lsb & 0x7F]

def addr_add(base, offset):
    """Add a flat byte offset to a 3-byte 7-bit address."""
    return _from_flat(_flat(base) + offset)

def addr_sub(a, b):
    """Subtract address b from address a; return flat integer difference."""
    return _flat(a) - _flat(b)

def checksum(data):
    """Roland checksum: (-sum(data)) & 0x7F"""
    return (-sum(data)) & 0x7F

# ---------------------------------------------------------------------------
# Memory regions to dump
# (address, size_bytes, label)
# Sizes are flat byte counts; we request in ≤256-byte chunks.
# ---------------------------------------------------------------------------
#
# Internal memory layout per the parameter map:
#   Patches    : 64 × 188 bytes  = 12032 bytes starting at [0x51,0x00,0x00]
#   Timbres    : 128 × 8 bytes   = 1024 bytes  starting at [0x05,0x00,0x00]
#   Tones      : 64 × 246 bytes  = 15744 bytes starting at [0x08,0x00,0x00]
#   Rhythm     : 85 × 4 bytes    = 340 bytes   starting at [0x09,0x00,0x00]
#   Part sett. : 3 × 8 bytes     = 24 bytes    starting at [0x52,0x01,0x00]
#   Sys setup  : 19 bytes                       at [0x52,0x00,0x00]
#   Patch chain: 5 × 50 bytes    = 250 bytes   starting at [0x52,0x02,0x00]
#
# Card bank patches occupy the same address space offset by 64 patches:
#   Card patches 65-128 start at [0x51,0x00,0x00] + 64*188 = [0x51,0x5C,0x44] + 188
#   = addr_add([0x51,0x5C,0x44], 188) = [0x51,0x5E,0x00]  (card bank start)
#
# NOTE: The manual states card patches are patches 65–128 in the same
# address space as internal patches 1–64, with bank flag distinguishing them
# via the Write Request mechanism. When reading, we read all 128 patch slots.

PATCH_STRIDE  = 188   # bytes per patch
PATCH_SIZE    = 188
TIMBRE_STRIDE = 8
TIMBRE_SIZE   = 8
TONE_STRIDE   = 256   # slot size (data=246, padding=10); see gr50_params ADDRESS_MAP
TONE_SIZE     = 246
RHYTHM_STRIDE = 4
RHYTHM_SIZE   = 4

INTERNAL_PATCH_BASE  = [0x51, 0x00, 0x00]
CARD_PATCH_BASE      = addr_add(INTERNAL_PATCH_BASE, 64 * PATCH_STRIDE)  # patches 65-128
TIMBRE_BASE          = [0x05, 0x00, 0x00]
TONE_BASE            = [0x08, 0x00, 0x00]
RHYTHM_BASE          = [0x09, 0x00, 0x00]
SYSTEM_SETUP_ADDR    = [0x52, 0x00, 0x00]
PART_SETTING_BASE    = [0x52, 0x01, 0x00]
PATCH_CHAIN_BASE     = [0x52, 0x02, 0x00]

WRITE_REQUEST_BASE   = [0x40, 0x00, 0x00]
WRITE_RESULT_ADDR    = [0x40, 0x10, 0x00]

# Write Request: patch sub-address within the write request block
WRITE_REQUEST_PATCH_OFFSET  = 0x0400   # Table 5, patch temporary
WRITE_REQUEST_TIMBRE_OFFSET = 0x0100   # Table 5, timbre temporary
# Tone write requests are at offset 0x00–0x1A within write request base

DUMP_REGIONS = [
    # (label,             base_address,         count, stride, item_size)
    # NOTE: patches_card and part_settings omitted — the GR-50 does not respond
    # to RQ1 for those addresses.
    ('patches_internal',  INTERNAL_PATCH_BASE,   64,  PATCH_STRIDE,  PATCH_SIZE),
    ('timbres',           TIMBRE_BASE,          128,  TIMBRE_STRIDE, TIMBRE_SIZE),
    ('tones',             TONE_BASE,             64,  TONE_STRIDE,   TONE_SIZE),
    ('rhythm_setups',     RHYTHM_BASE,           85,  RHYTHM_STRIDE, RHYTHM_SIZE),
    ('system_setup',      SYSTEM_SETUP_ADDR,      1,  0,             19),
    ('patch_chains',      PATCH_CHAIN_BASE,       5,  50,            50),
]

# ---------------------------------------------------------------------------
# MIDI I/O wrapper
# ---------------------------------------------------------------------------

class MidiPort:
    def __init__(self, port_name_hint=None):
        self._midi_in  = rtmidi.MidiIn()
        self._midi_out = rtmidi.MidiOut()
        self._rx_buf   = []
        self._lock     = threading.Lock()
        self._event    = threading.Event()

        in_ports  = self._midi_in.get_ports()
        out_ports = self._midi_out.get_ports()

        if not in_ports:
            raise RuntimeError("No MIDI input ports found.")
        if not out_ports:
            raise RuntimeError("No MIDI output ports found.")

        # Choose port
        in_idx  = self._pick(in_ports,  port_name_hint, "input")
        out_idx = self._pick(out_ports, port_name_hint, "output")

        self._midi_in.open_port(in_idx)
        self._midi_out.open_port(out_idx)
        self._midi_in.ignore_types(sysex=False)   # we WANT sysex
        self._midi_in.set_callback(self._rx_callback)

        print(f"MIDI in:  {in_ports[in_idx]}")
        print(f"MIDI out: {out_ports[out_idx]}")

    def _pick(self, ports, hint, direction):
        if hint:
            for i, p in enumerate(ports):
                if hint.lower() in p.lower():
                    return i
            print(f"Warning: '{hint}' not found in {direction} ports. Available:")
            for i, p in enumerate(ports):
                print(f"  {i}: {p}")
        if len(ports) == 1:
            return 0
        print(f"\nAvailable MIDI {direction} ports:")
        for i, p in enumerate(ports):
            print(f"  {i}: {p}")
        while True:
            try:
                idx = int(input(f"Select {direction} port number: "))
                if 0 <= idx < len(ports):
                    return idx
            except (ValueError, KeyboardInterrupt):
                pass

    def _rx_callback(self, event, data=None):
        msg, _ = event
        with self._lock:
            self._rx_buf.append(bytes(msg))
        self._event.set()

    def send(self, data):
        self._midi_out.send_message(list(data))

    def flush_rx(self):
        with self._lock:
            self._rx_buf.clear()
        self._event.clear()

    def recv_sysex(self, timeout=TIMEOUT_S):
        """Wait for the next complete SysEx message."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            got = self._event.wait(timeout=remaining)
            if not got:
                return None
            self._event.clear()
            with self._lock:
                for msg in list(self._rx_buf):
                    if msg and msg[0] == 0xF0 and msg[-1] == 0xF7:
                        self._rx_buf.remove(msg)
                        return msg

    def close(self):
        self._midi_in.close_port()
        self._midi_out.close_port()

# ---------------------------------------------------------------------------
# SysEx message builders
# ---------------------------------------------------------------------------

def build_rq1(device_id, address, size_bytes):
    """Build RQ1 (one-way data request).
    size_bytes is a flat integer; encoded as 3-byte 7-bit size field."""
    size = _from_flat(size_bytes)
    body = address + size
    return bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_RQ1] +
                 body + [checksum(body), 0xF7])

def build_dt1(device_id, address, data):
    """Build DT1 messages (split at MAX_PAYLOAD)."""
    messages = []
    data = list(data)
    for i in range(0, max(len(data), 1), MAX_PAYLOAD):
        chunk = data[i:i + MAX_PAYLOAD]
        addr  = addr_add(address, i)
        body  = addr + chunk
        messages.append(bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_DT1] +
                               body + [checksum(body), 0xF7]))
    return messages

def build_wsd(device_id, address, size_bytes):
    size = _from_flat(size_bytes)
    body = address + size
    return bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_WSD] +
                 body + [checksum(body), 0xF7])

def build_rqd(device_id, address, size_bytes):
    size = _from_flat(size_bytes)
    body = address + size
    return bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_RQD] +
                 body + [checksum(body), 0xF7])

def build_ack(device_id):
    return bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_ACK, 0xF7])

def build_eod(device_id):
    return bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_EOD, 0xF7])

def build_err(device_id):
    return bytes([0xF0, ROLAND_ID, device_id, MODEL_ID, CMD_ERR, 0xF7])

# ---------------------------------------------------------------------------
# SysEx parsing
# ---------------------------------------------------------------------------

def parse_sysex(msg):
    """Parse a SysEx message. Returns dict with keys: cmd, address, data, valid."""
    if not msg or msg[0] != 0xF0 or msg[-1] != 0xF7:
        return None
    if len(msg) < 6:
        return None
    if msg[1] != ROLAND_ID or msg[3] != MODEL_ID:
        return None
    cmd = msg[4]
    if cmd in (CMD_ACK, CMD_EOD, CMD_ERR, CMD_RJC):
        return {'cmd': cmd, 'address': None, 'data': None, 'valid': True}
    if cmd in (CMD_DT1, CMD_DAT):
        if len(msg) < 10:
            return None
        address = list(msg[5:8])
        data    = list(msg[8:-2])
        csum    = msg[-2]
        body    = list(msg[5:-1])
        valid   = checksum(body) == 0
        return {'cmd': cmd, 'address': address, 'data': data, 'valid': valid}
    return {'cmd': cmd, 'address': None, 'data': None, 'valid': True}

# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def read_region(midi, device_id, label, base_addr, count, stride, item_size, verbose=True):
    """Read `count` items of `item_size` bytes each from consecutive addresses.
    Returns list of bytearrays, one per item."""
    items = []
    for i in range(count):
        addr = addr_add(base_addr, i * stride)
        item_data = bytearray()
        offset = 0
        while offset < item_size:
            chunk_size = min(MAX_PAYLOAD, item_size - offset)
            req_addr   = addr_add(addr, offset)
            msg = build_rq1(device_id, req_addr, chunk_size)
            midi.flush_rx()
            midi.send(msg)
            resp = midi.recv_sysex(timeout=TIMEOUT_S)
            if resp is None:
                raise TimeoutError(
                    f"No response reading {label}[{i}] offset {offset:#04x}")
            parsed = parse_sysex(resp)
            if parsed is None or not parsed['valid']:
                raise ValueError(
                    f"Invalid/checksum-failed response for {label}[{i}] offset {offset:#04x}")
            if parsed['cmd'] != CMD_DT1:
                raise ValueError(
                    f"Expected DT1, got cmd={parsed['cmd']:#04x} for {label}[{i}]")
            item_data.extend(parsed['data'][:chunk_size])
            offset += chunk_size
            time.sleep(0.10)  # 100 ms recovery gap before next RQ1
        items.append(item_data)
        if verbose and (i % 8 == 0 or i == count - 1):
            print(f"  {label}: {i+1}/{count}", end='\r', flush=True)
    if verbose:
        print(f"  {label}: {count}/{count} ✓")
    return items

# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_region_dt1(midi, device_id, label, base_addr, items, stride, verbose=True):
    """Write items via DT1 (one-way). Each item is a bytes-like."""
    for i, item in enumerate(items):
        addr = addr_add(base_addr, i * stride)
        msgs = build_dt1(device_id, addr, list(item))
        for msg in msgs:
            midi.send(msg)
            time.sleep(0.025)  # ≥20 ms inter-message gap per manual
        if verbose and (i % 8 == 0 or i == len(items) - 1):
            print(f"  {label}: {i+1}/{len(items)}", end='\r', flush=True)
    if verbose:
        print(f"  {label}: {len(items)}/{len(items)} ✓")

def write_patch_to_card(midi, device_id, internal_idx, card_slot, patch_data, verbose=True):
    """
    Write one patch to card slot `card_slot` (0-based, so card patches 1-64).

    Strategy (per manual §3.3.2.5 Write Request):
      1. Send the patch data to Patch Temporary area [0x50,0x00,0x00].
      2. Send a Write Request to [0x40,0x00,0x00] + patch offset (0x0400),
         with the target slot number and bank=1 (card).
      3. Poll Write Result at [0x40,0x10,0x00] for success.

    The GR-50 handles card formatting automatically if the card is new.
    """
    # Step 1: Load patch into temporary area
    patch_temp_addr = [0x50, 0x00, 0x00]
    msgs = build_dt1(device_id, patch_temp_addr, list(patch_data))
    for msg in msgs:
        midi.send(msg)
        time.sleep(0.025)

    # Step 2: Issue Write Request — patch to card slot
    # Write request patch offset within the write request block = 0x0400
    wr_patch_addr = addr_add(WRITE_REQUEST_BASE, WRITE_REQUEST_PATCH_OFFSET)
    # Target spec: [patch_number (0-based, 0-63), bank (0=internal, 1=card)]
    wr_data = [card_slot & 0x3F, 0x01]   # bank=1 → card
    msgs = build_dt1(device_id, wr_patch_addr, wr_data)
    for msg in msgs:
        midi.send(msg)
        time.sleep(0.025)

    # Step 3: Poll Write Result
    time.sleep(0.1)
    result_msg = build_rq1(device_id, WRITE_RESULT_ADDR, 1)
    midi.flush_rx()
    midi.send(result_msg)
    resp = midi.recv_sysex(timeout=TIMEOUT_S * 2)
    if resp is None:
        raise TimeoutError(f"No write result for card slot {card_slot+1}")
    parsed = parse_sysex(resp)
    if parsed and parsed['data']:
        result_code = parsed['data'][0] & 0x03
        result_names = ['OK', 'Card Not Ready', 'Write Protected', 'Reserved']
        if result_code != 0:
            raise IOError(
                f"Card write failed for slot {card_slot+1}: {result_names[result_code]}")

    if verbose:
        print(f"  card slot {card_slot+1:2d}: written ✓")

# ---------------------------------------------------------------------------
# Dump command
# ---------------------------------------------------------------------------

def cmd_dump(args):
    midi = MidiPort(args.port)
    device_id = 0x10 + (args.unit - 1)   # Unit 1 → 0x10, Unit 16 → 0x1F

    print(f"\nDumping GR-50 (unit {args.unit}, device_id={device_id:#04x})...")

    dump = {
        'meta': {
            'tool':      'gr50_tool.py',
            'timestamp': datetime.datetime.now().isoformat(),
            'unit':      args.unit,
            'device_id': device_id,
        },
        'regions': {}
    }

    try:
        for label, base_addr, count, stride, item_size in DUMP_REGIONS:
            print(f"\n[{label}]")
            try:
                items = read_region(midi, device_id, label, base_addr,
                                    count, stride, item_size)
                dump['regions'][label] = {
                    'base_address': base_addr,
                    'stride':       stride,
                    'item_size':    item_size,
                    'items':        [item.hex() for item in items],
                }
            except (TimeoutError, ValueError) as e:
                print(f"\n  WARNING: {e}")
                dump['regions'][label] = {'error': str(e), 'items': []}

    finally:
        midi.close()

    out_path = Path(args.out)
    out_path.write_text(json.dumps(dump, indent=2))
    print(f"\nDump saved to: {out_path}")
    _print_dump_summary(dump)

def _print_dump_summary(dump):
    print("\n--- Dump summary ---")
    for label, region in dump['regions'].items():
        if 'error' in region:
            print(f"  {label:25s}  ERROR: {region['error']}")
        else:
            n = len(region['items'])
            sz = region['item_size'] if 'item_size' in region else '?'
            print(f"  {label:25s}  {n} × {sz} bytes")

    patches = dump['regions'].get('patches_internal', {}).get('items', [])
    if patches:
        print("\n--- Internal patch names ---")
        for i, p_hex in enumerate(patches):
            data = bytes.fromhex(p_hex)
            name = _decode_patch_name(data)
            print(f"  {i+1:3d}: {name}")

    _print_tones_summary(dump)
    _print_timbres_summary(dump)
    _print_rhythm_summary(dump)
    _print_system_setup_summary(dump)
    _print_chains_summary(dump)

def _decode_patch_name(patch_data):
    try:
        chars = [chr(b) if 32 <= b <= 127 else '?' for b in patch_data[:16]]
        return ''.join(chars).rstrip()
    except Exception:
        return '(decode error)'

def _decode_tone_name(tone_data):
    try:
        chars = [chr(b) if 32 <= b <= 127 else '?' for b in tone_data[:10]]
        return ''.join(chars).rstrip()
    except Exception:
        return '(decode error)'

_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_TIMBRE_GROUPS = ('a', 'b', 'i/c', 'l')

def _timbre_id(idx):   # 0-based → A-11 … B-88
    bank = 'A' if idx < 64 else 'B'
    p = idx % 64
    return f"{bank}-{p//8+1}{p%8+1}"

def _patch_id(n):      # 0-based, 0-63=I, 64-127=C
    bank = 'I' if n < 64 else 'C'
    p = n % 64
    return f"{bank}-{p//8+1}{p%8+1}"

def _rhythm_note(idx): # 0-based, 0=C1 … 84=C8
    return f"{_NOTE_NAMES[idx % 12]}{idx // 12 + 1}"

def _print_tones_summary(dump):
    items = dump['regions'].get('tones', {}).get('items', [])
    if not items:
        return
    print("\n--- Tone names ---")
    for i, h in enumerate(items):
        name = _decode_tone_name(bytes.fromhex(h))
        label = f"i{i+1:02d}"
        print(f"  {label}: {name}")

def _print_timbres_summary(dump):
    items = dump['regions'].get('timbres', {}).get('items', [])
    if not items:
        return
    print("\n--- Timbres (group / tone#) ---")
    for i, h in enumerate(items):
        d = bytes.fromhex(h)
        grp  = _TIMBRE_GROUPS[d[0] & 0x03] if d[0] < 4 else '?'
        tone = (d[1] & 0x3F) + 1
        tid  = _timbre_id(i)
        print(f"  {tid}: {grp}-{tone:02d}")

def _print_rhythm_summary(dump):
    items = dump['regions'].get('rhythm_setups', {}).get('items', [])
    if not items:
        return
    print("\n--- Rhythm setups (note → tone#) ---")
    for i, h in enumerate(items):
        d = bytes.fromhex(h)
        tone  = (d[0] & 0x3F) + 1
        level = d[1] & 0x7F
        note  = _rhythm_note(i)
        print(f"  {note:4s}: r{tone:02d}  level={level}")

def _print_system_setup_summary(dump):
    items = dump['regions'].get('system_setup', {}).get('items', [])
    if not items:
        return
    d = bytes.fromhex(items[0])
    ctrl_ch = d[1] & 0x1F
    ctrl_str = 'Off' if ctrl_ch == 16 else str(ctrl_ch + 1)
    print("\n--- System setup ---")
    print(f"  Master tune     : {d[0]} (0=435.6Hz … 127=446.2Hz)")
    print(f"  Control channel : {ctrl_str}")
    print(f"  Display mode    : {d[2]}")
    print(f"  MIDI bender     : {d[3]}")
    print(f"  MIDI modulation : {'on' if d[4] else 'off'}")
    print(f"  MIDI volume     : {'on' if d[5] else 'off'}")
    print(f"  String sens     : {list(d[13:19])}")

def _print_chains_summary(dump):
    items = dump['regions'].get('patch_chains', {}).get('items', [])
    if not items:
        return
    chain_labels = ['1A', '1B', '1C', '1D', '1E']
    print("\n--- Patch chains ---")
    for i, h in enumerate(items):
        d = bytes.fromhex(h)
        label = chain_labels[i] if i < len(chain_labels) else str(i+1)
        steps = []
        for s in range(25):
            end_mark    = d[s * 2] & 0x01
            patch_num   = d[s * 2 + 1] & 0x7F
            if end_mark:
                break
            steps.append(_patch_id(patch_num))
        print(f"  Chain {label}: {' → '.join(steps) if steps else '(empty)'}")

# ---------------------------------------------------------------------------
# Write command
# ---------------------------------------------------------------------------

def cmd_write(args):
    dump_path = Path(args.dump)
    if not dump_path.exists():
        print(f"ERROR: dump file not found: {dump_path}")
        sys.exit(1)

    dump = json.loads(dump_path.read_text())
    meta = dump.get('meta', {})
    print(f"Dump from: {meta.get('timestamp','?')}  unit={meta.get('unit','?')}")

    # Validate bank choice and get patch list
    bank = args.bank.lower()
    if bank == 'internal':
        region_key = 'patches_internal'
    elif bank == 'card':
        region_key = 'patches_card'
    else:
        print(f"ERROR: --bank must be 'internal' or 'card'")
        sys.exit(1)

    patch_region = dump['regions'].get(region_key, {})
    if 'error' in patch_region:
        print(f"ERROR: patch region '{region_key}' failed during dump: {patch_region['error']}")
        sys.exit(1)
    patch_items = patch_region.get('items', [])
    if not patch_items:
        print(f"ERROR: no patches in region '{region_key}'")
        sys.exit(1)

    patches = [bytes.fromhex(h) for h in patch_items]

    print(f"\nPatches to write ({bank} bank): {len(patches)}")
    for i, p in enumerate(patches):
        print(f"  {i+1:3d}: {_decode_patch_name(p)}")

    dest = args.dest.lower()
    if dest not in ('internal', 'card'):
        print("ERROR: --dest must be 'internal' or 'card'")
        sys.exit(1)

    print(f"\nDestination: {dest}")
    if dest == 'card':
        print("NOTE: The GR-50 will format/initialize the card automatically")
        print("      if it contains no valid GR-50 data (new or foreign card).")
        print("      Make sure the card's write-protect switch is OFF.")
    elif dest == 'internal':
        print("WARNING: This will overwrite internal patch memory.")

    confirm = input("\nProceed? [y/N] ").strip().lower()
    if confirm != 'y':
        print("Aborted.")
        sys.exit(0)

    midi = MidiPort(args.port)
    device_id = 0x10 + (args.unit - 1)
    print(f"\nWriting to GR-50 (unit {args.unit}, device_id={device_id:#04x})...")

    try:
        if dest == 'internal':
            print(f"\n[Writing {len(patches)} patches to internal memory]")
            write_region_dt1(midi, device_id, 'patches_internal',
                             INTERNAL_PATCH_BASE, patches, PATCH_STRIDE)

        elif dest == 'card':
            print(f"\n[Writing {len(patches)} patches to memory card]")
            print("  (The GR-50 handles card formatting if needed.)")
            for i, patch_data in enumerate(patches):
                write_patch_to_card(midi, device_id,
                                    internal_idx=i,
                                    card_slot=i,
                                    patch_data=patch_data)

    except (TimeoutError, IOError) as e:
        print(f"\nERROR: {e}")
        midi.close()
        sys.exit(1)
    finally:
        midi.close()

    print("\nWrite complete.")

# ---------------------------------------------------------------------------
# List MIDI ports helper
# ---------------------------------------------------------------------------

def cmd_list_ports(_args):
    midi_in  = rtmidi.MidiIn()
    midi_out = rtmidi.MidiOut()
    print("MIDI input ports:")
    for i, p in enumerate(midi_in.get_ports()):
        print(f"  {i}: {p}")
    print("MIDI output ports:")
    for i, p in enumerate(midi_out.get_ports()):
        print(f"  {i}: {p}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Roland GR-50 memory dump and card writer')
    parser.add_argument('--port', default=None,
        help='MIDI port name substring to auto-select (e.g. "GR-50", "USB")')
    parser.add_argument('--unit', type=int, default=1,
        help='GR-50 Unit number (1–16, matches System Setup; default 1)')

    sub = parser.add_subparsers(dest='command', required=True)

    # dump
    p_dump = sub.add_parser('dump', help='Read GR-50 memory to a .gr50 file')
    p_dump.add_argument('--out', default='gr50_dump.gr50',
        help='Output file path (default: gr50_dump.gr50)')
    p_dump.set_defaults(func=cmd_dump)

    # write
    p_write = sub.add_parser('write',
        help='Write a patch bank from a dump file to internal or card memory')
    p_write.add_argument('--dump', required=True,
        help='Path to .gr50 dump file')
    p_write.add_argument('--bank', default='internal',
        choices=['internal', 'card'],
        help='Which bank from the dump to use (default: internal)')
    p_write.add_argument('--dest', default='card',
        choices=['internal', 'card'],
        help='Destination on the GR-50 (default: card)')
    p_write.set_defaults(func=cmd_write)

    # show
    p_show = sub.add_parser('show', help='Print summary of a saved .gr50 dump file')
    p_show.add_argument('--dump', default='gr50_dump.gr50',
        help='Path to .gr50 dump file (default: gr50_dump.gr50)')
    p_show.set_defaults(func=lambda a: _print_dump_summary(
        json.loads(Path(a.dump).read_text())))

    # ports
    p_ports = sub.add_parser('ports', help='List available MIDI ports')
    p_ports.set_defaults(func=cmd_list_ports)

    args = parser.parse_args()
    args.func(args)

if __name__ == '__main__':
    main()
