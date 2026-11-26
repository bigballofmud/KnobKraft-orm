#
#   Copyright (c) 2026 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#
#   Roland GR-50 Guitar Synthesizer
#
#   Uses Roland Exclusive Format Type IV (same family as the D-50).
#     Manufacturer ID : 0x41
#     Model ID        : 0x16
#     Device ID       : Unit# - 1, range 0x10–0x1F
#     Address space   : 3 bytes, 7-bit each (0x00–0x7F)
#     Checksum        : (-sum(address + data)) & 0x7F
#
#   Two banks are managed:
#     Bank 0 — Internal Patches (programs 0–63), 188 bytes each
#       Edit buffer  : [0x50, 0x00, 0x00]
#       Memory       : [0x51, 0x00, 0x00], stride 188 bytes
#     Bank 1 — User Tones (programs 64–127), 246 bytes each
#       Edit buffer  : [0x04, 0x00, 0x00]  (Tone Temporary, string 1 slot 1)
#       Memory       : [0x08, 0x00, 0x00], stride 256 bytes (246 data + 10 padding)
#
#   Patches reference tones by group/number (a/b = preset ROM, i/c = user/card).
#   Preset tones (groups a and b) live in ROM and are not SysEx-accessible.
#

import hashlib
from typing import Dict, List, Optional, Tuple

import knobkraft

ROLAND_ID   = 0x41
MODEL_ID    = 0x16      # GR-50
COMMAND_RQ1 = 0x11      # one-way request
COMMAND_DT1 = 0x12      # one-way data-set

DEFAULT_DEVICE_ID  = 0x10   # Unit 1 → device ID 0x10

PATCH_SIZE         = 188
PATCH_COUNT        = 64
PATCH_NAME_LENGTH  = 16     # ASCII bytes at offset 0 of the patch common block
PATCH_TEMP_BASE    = [0x50, 0x00, 0x00]   # Patch Temporary (edit buffer)
PATCH_MEMORY_BASE  = [0x51, 0x00, 0x00]   # Internal patch bank start

TONE_SIZE          = 246
TONE_COUNT         = 64
TONE_NAME_LENGTH   = 10     # ASCII bytes at offset 0 of the tone common block
TONE_STRIDE        = 256    # slot size; only 246 bytes are tone data, 10 are padding
TONE_TEMP_BASE     = [0x04, 0x00, 0x00]   # Tone Temporary (string 1, slot 1)
TONE_MEMORY_BASE   = [0x08, 0x00, 0x00]   # User tone bank start
TONE_MAX_PAYLOAD   = 64         # GR-50 max reliable chunk size for RQ1.
                                # The GR-50 only answers the *first* RQ1 in a burst of multiple
                                # requests; all subsequent requests in the same sendBlock are silently
                                # ignored.  We work around this by sending only the first chunk in
                                # createProgramDumpRequest and using isPartOfSingleProgramDump's
                                # (bool, handshake_bytes) tuple return to trigger each next chunk
                                # sequentially, exactly as gr50_tool.py's recv-then-send loop does.

SYSTEM_SETUP_ADDR  = [0x52, 0x00, 0x00]   # used for device detection
SYSTEM_SETUP_SIZE  = 19

_device_id = DEFAULT_DEVICE_ID


# ---------------------------------------------------------------------------
# 7-bit address arithmetic
# ---------------------------------------------------------------------------

def _addr_to_int(addr: List[int]) -> int:
    return (addr[0] << 14) | (addr[1] << 7) | addr[2]


def _int_to_addr(n: int) -> List[int]:
    return [(n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F]


def _size_as_7bit(n: int) -> List[int]:
    return _int_to_addr(n)


def _patch_address(patch_no: int) -> List[int]:
    base = _addr_to_int(PATCH_MEMORY_BASE)
    return _int_to_addr(base + (patch_no % PATCH_COUNT) * PATCH_SIZE)


def _tone_address(tone_no: int) -> List[int]:
    base = _addr_to_int(TONE_MEMORY_BASE)
    return _int_to_addr(base + (tone_no % TONE_COUNT) * TONE_STRIDE)


# ---------------------------------------------------------------------------
# SysEx building and parsing
# ---------------------------------------------------------------------------

def _roland_checksum(data: List[int]) -> int:
    return sum(-x for x in data) & 0x7F


def _build_message(device_id: int, command: int, address: List[int], data: List[int]) -> List[int]:
    body = address + data
    return [0xF0, ROLAND_ID, device_id & 0x1F, MODEL_ID, command] + body + [_roland_checksum(body), 0xF7]


def _parse_message(message: List[int]) -> Tuple[int, List[int], List[int]]:
    if not isOwnSysex(message):
        raise ValueError("Not a GR-50 SysEx message")
    body = message[5:-2]
    expected = _roland_checksum(body)
    if expected != message[-2]:
        raise ValueError(f"Checksum error: expected {expected:#04x}, got {message[-2]:#04x}")
    return message[4], list(message[5:8]), list(message[8:-2])


# ---------------------------------------------------------------------------
# Patch recognition helpers
# ---------------------------------------------------------------------------

def _is_temp_patch(address: List[int], data_length: int) -> bool:
    return address == PATCH_TEMP_BASE and data_length == PATCH_SIZE


def _patch_no_from_address(address: List[int]) -> Optional[int]:
    delta = _addr_to_int(address) - _addr_to_int(PATCH_MEMORY_BASE)
    if delta < 0 or delta >= PATCH_COUNT * PATCH_SIZE or delta % PATCH_SIZE != 0:
        return None
    return delta // PATCH_SIZE


def _extract_patch_data(messages: List[int]) -> Tuple[Optional[int], List[int]]:
    """Scan a flat sysex byte list and return (patch_no or None, 188-byte data).

    Returns patch_no=None for an edit-buffer (Patch Temporary) message,
    or patch_no=0..63 for a program-memory message.
    """
    for start, end in knobkraft.sysex.findSysexDelimiters(messages):
        msg = messages[start:end]
        if not isOwnSysex(msg):
            continue
        try:
            command, address, data = _parse_message(msg)
        except ValueError:
            continue
        if command != COMMAND_DT1 or len(data) != PATCH_SIZE:
            continue
        if _is_temp_patch(address, len(data)):
            return None, data
        patch_no = _patch_no_from_address(address)
        if patch_no is not None:
            return patch_no, data
    raise ValueError("No valid GR-50 patch message found")


# ---------------------------------------------------------------------------
# Tone recognition helpers
# ---------------------------------------------------------------------------

def _is_temp_tone(address: List[int], data_length: int) -> bool:
    return address == TONE_TEMP_BASE and data_length == TONE_SIZE


def _tone_no_from_address(address: List[int]) -> Optional[int]:
    delta = _addr_to_int(address) - _addr_to_int(TONE_MEMORY_BASE)
    if delta < 0 or delta >= TONE_COUNT * TONE_STRIDE or delta % TONE_STRIDE != 0:
        return None
    return delta // TONE_STRIDE


def _extract_tone_data(messages: List[int]) -> Tuple[Optional[int], List[int]]:
    """Scan a flat sysex byte list and return (tone_no or None, 246-byte data).

    Returns tone_no=None for an edit-buffer (Tone Temporary) message,
    or tone_no=0..63 for a memory message.  Handles both a single full-size
    DT1 and the chunked DT1s produced by createProgramDumpRequest.
    """
    tone_base_flat = _addr_to_int(TONE_MEMORY_BASE)
    temp_base_flat = _addr_to_int(TONE_TEMP_BASE)

    # slot (int or None for temp) -> {offset: data_bytes}
    slots: Dict[Optional[int], Dict[int, List[int]]] = {}

    for start, end in knobkraft.sysex.findSysexDelimiters(messages):
        msg = messages[start:end]
        if not isOwnSysex(msg):
            continue
        try:
            command, address, data = _parse_message(msg)
        except ValueError:
            continue
        if command != COMMAND_DT1:
            continue

        addr_flat = _addr_to_int(address)

        if addr_flat == temp_base_flat and len(data) == TONE_SIZE:
            return None, data

        delta = addr_flat - tone_base_flat
        if 0 <= delta < TONE_COUNT * TONE_STRIDE:
            slot = delta // TONE_STRIDE
            offset = delta % TONE_STRIDE
            # Accept both RQ1-driven chunks (≤64 bytes) and bulk-dump DT1s
            # (256 bytes = full TONE_STRIDE slot).  Clip padding so stored
            # data never exceeds TONE_SIZE regardless of message length.
            if offset < TONE_SIZE and offset + len(data) <= TONE_STRIDE:
                slots.setdefault(slot, {})[offset] = data[:TONE_SIZE - offset]

    for slot, chunk_map in slots.items():
        assembled: List[int] = []
        expected = 0
        for off in sorted(chunk_map):
            if off != expected:
                break
            assembled.extend(chunk_map[off])
            expected += len(chunk_map[off])
        else:
            if len(assembled) == TONE_SIZE:
                return slot, assembled

    raise ValueError("No valid GR-50 tone message found")


# ---------------------------------------------------------------------------
# KnobKraft API
# ---------------------------------------------------------------------------

def name() -> str:
    return "Roland GR-50"


def bankDescriptors() -> List[Dict]:
    return [
        {"bank": 0, "name": "Internal Patches", "size": PATCH_COUNT, "type": "Patch"},
        {"bank": 1, "name": "User Tones",        "size": TONE_COUNT,  "type": "Tone"},
    ]


def friendlyProgramName(program: int) -> str:
    if program >= PATCH_COUNT:
        tone = (program - PATCH_COUNT) % TONE_COUNT
        return f"i{tone + 1:02d}"
    patch = program % PATCH_COUNT
    return f"I-{patch // 8 + 1}{patch % 8 + 1}"


def generalMessageDelay() -> int:
    # KnobKraft sleeps this long before sending every message, including each handshake RQ1.
    # The GR-50 ignores an RQ1 that arrives too soon after it finished sending a DT1:
    # measured on hardware (2026-11-25), 0 ms and 50 ms both stall on the second chunk,
    # 75 ms and 100 ms complete all 64 tones.  100 ms keeps a margin over that threshold.
    return 100


def isOwnSysex(message: List[int]) -> bool:
    return (
        len(message) >= 10
        and message[0] == 0xF0
        and message[1] == ROLAND_ID
        and message[3] == MODEL_ID
        and message[-1] == 0xF7
    )


def createDeviceDetectMessage(channel: int) -> List[int]:
    device_id = (channel + 0x10) & 0x1F
    return _build_message(device_id, COMMAND_RQ1, SYSTEM_SETUP_ADDR, _size_as_7bit(SYSTEM_SETUP_SIZE))


def needsChannelSpecificDetection() -> bool:
    return True


def channelIfValidDeviceResponse(message: List[int]) -> int:
    global _device_id
    if not isOwnSysex(message):
        return -1
    try:
        command, address, data = _parse_message(message)
    except ValueError:
        return -1
    if command == COMMAND_DT1 and address == SYSTEM_SETUP_ADDR:
        _device_id = message[2]
        # Return the device-ID offset (Unit# - 1), not the GR-50's basic MIDI channel
        # stored in data[1].  KnobKraft saves this value as the synth's "channel" and
        # passes it back to createDeviceDetectMessage for the startup check, which
        # turns it into device ID 0x10 + channel.  Returning the basic channel made
        # that check address the wrong unit (e.g. 0x1F instead of 0x10).
        return message[2] & 0x0F
    return -1


def createEditBufferRequest(channel: int) -> List[int]:
    return _build_message(_device_id, COMMAND_RQ1, PATCH_TEMP_BASE, _size_as_7bit(PATCH_SIZE))


def isPartOfEditBufferDump(message: List[int]) -> bool:
    if not isOwnSysex(message):
        return False
    try:
        command, address, data = _parse_message(message)
    except ValueError:
        return False
    return command == COMMAND_DT1 and (
        _is_temp_patch(address, len(data)) or _is_temp_tone(address, len(data))
    )


def isEditBufferDump(messages: List[int]) -> bool:
    try:
        patch_no, _ = _extract_patch_data(messages)
        return patch_no is None
    except ValueError:
        pass
    try:
        tone_no, _ = _extract_tone_data(messages)
        return tone_no is None
    except ValueError:
        pass
    return False


def createProgramDumpRequest(channel: int, patchNo: int) -> List[int]:
    if patchNo >= PATCH_COUNT:
        tone_no = (patchNo - PATCH_COUNT) % TONE_COUNT
        base_flat = _addr_to_int(_tone_address(tone_no))
        # Send only the first chunk.  isPartOfSingleProgramDump returns a
        # (True, next_rq1) handshake tuple for every non-final chunk so the
        # C++ layer drives each subsequent request after the previous DT1
        # arrives, matching the strict sequential pattern gr50_tool.py uses.
        return _build_message(_device_id, COMMAND_RQ1,
                              _int_to_addr(base_flat),
                              _size_as_7bit(TONE_MAX_PAYLOAD))
    return _build_message(_device_id, COMMAND_RQ1, _patch_address(patchNo), _size_as_7bit(PATCH_SIZE))


def isPartOfSingleProgramDump(message: List[int]):
    if not isOwnSysex(message):
        return False
    try:
        command, address, data = _parse_message(message)
    except ValueError:
        return False
    if command != COMMAND_DT1:
        return False
    if _patch_no_from_address(address) is not None and len(data) == PATCH_SIZE:
        return True
    # Accept any DT1 whose address falls within a tone slot (chunked or full)
    tone_base_flat = _addr_to_int(TONE_MEMORY_BASE)
    addr_flat = _addr_to_int(address)
    delta = addr_flat - tone_base_flat
    if 0 <= delta < TONE_COUNT * TONE_STRIDE:
        slot = delta // TONE_STRIDE
        offset_in_slot = delta % TONE_STRIDE
        # Accept RQ1-driven chunks (≤TONE_MAX_PAYLOAD) and bulk-dump DT1s
        # (TONE_STRIDE bytes).  Clip to TONE_SIZE for the "bytes remaining"
        # calculation so a 256-byte bulk message is treated as complete.
        if offset_in_slot < TONE_SIZE and offset_in_slot + len(data) <= TONE_STRIDE:
            stored_len = min(len(data), TONE_SIZE - offset_in_slot)
            next_offset = offset_in_slot + stored_len
            if next_offset < TONE_SIZE:
                # More data needed: return (True, next_RQ1) so the C++ layer
                # sends the next request only after this DT1 has arrived,
                # keeping requests strictly sequential (like gr50_tool.py).
                slot_base = tone_base_flat + slot * TONE_STRIDE
                next_size = min(TONE_MAX_PAYLOAD, TONE_SIZE - next_offset)
                next_rq1 = _build_message(_device_id, COMMAND_RQ1,
                                          _int_to_addr(slot_base + next_offset),
                                          _size_as_7bit(next_size))
                return True, next_rq1
            else:
                return True
    return False


def isSingleProgramDump(messages: List[int]) -> bool:
    try:
        patch_no, _ = _extract_patch_data(messages)
        return patch_no is not None
    except ValueError:
        pass
    try:
        tone_no, _ = _extract_tone_data(messages)
        return tone_no is not None
    except ValueError:
        pass
    return False


def convertToEditBuffer(channel: int, messages: List[int]) -> List[int]:
    try:
        _, data = _extract_patch_data(messages)
        return _build_message(_device_id, COMMAND_DT1, PATCH_TEMP_BASE, data)
    except ValueError:
        pass
    _, data = _extract_tone_data(messages)
    return _build_message(_device_id, COMMAND_DT1, TONE_TEMP_BASE, data)


def convertToProgramDump(channel: int, messages: List[int], program_number: int) -> List[int]:
    # The kind of data decides the bank (a tone can only live in a tone slot, a patch in a patch
    # slot); the program number only picks the slot within that bank.  Reading the bank from the
    # program number instead would crash when a tone is sent to a patch slot or vice versa.
    try:
        _, data = _extract_patch_data(messages)
        return _build_message(_device_id, COMMAND_DT1, _patch_address(program_number % PATCH_COUNT), data)
    except ValueError:
        pass
    _, data = _extract_tone_data(messages)
    return _build_message(_device_id, COMMAND_DT1, _tone_address(program_number % TONE_COUNT), data)


def numberFromDump(messages: List[int]) -> int:
    try:
        patch_no, _ = _extract_patch_data(messages)
        return patch_no if patch_no is not None else 0
    except ValueError:
        pass
    try:
        tone_no, _ = _extract_tone_data(messages)
        return PATCH_COUNT + (tone_no if tone_no is not None else 0)
    except ValueError:
        return 0


def nameFromDump(messages: List[int]) -> str:
    try:
        _, data = _extract_patch_data(messages)
        return bytes(data[:PATCH_NAME_LENGTH]).decode("ascii", errors="replace").rstrip()
    except ValueError:
        pass
    try:
        _, data = _extract_tone_data(messages)
        return bytes(data[:TONE_NAME_LENGTH]).decode("ascii", errors="replace").rstrip()
    except ValueError:
        return "Invalid"


def renamePatch(messages: List[int], new_name: str) -> List[int]:
    try:
        patch_no, data = _extract_patch_data(messages)
        encoded = list((new_name or "")[:PATCH_NAME_LENGTH].ljust(PATCH_NAME_LENGTH).encode("ascii", errors="replace"))
        data[:PATCH_NAME_LENGTH] = encoded
        if patch_no is None:
            return _build_message(_device_id, COMMAND_DT1, PATCH_TEMP_BASE, data)
        return _build_message(_device_id, COMMAND_DT1, _patch_address(patch_no), data)
    except ValueError:
        pass
    tone_no, data = _extract_tone_data(messages)
    encoded = list((new_name or "")[:TONE_NAME_LENGTH].ljust(TONE_NAME_LENGTH).encode("ascii", errors="replace"))
    data[:TONE_NAME_LENGTH] = encoded
    if tone_no is None:
        return _build_message(_device_id, COMMAND_DT1, TONE_TEMP_BASE, data)
    return _build_message(_device_id, COMMAND_DT1, _tone_address(tone_no), data)


def blankedOut(messages: List[int]) -> List[int]:
    try:
        _, data = _extract_patch_data(messages)
        blanked = data.copy()
        blanked[:PATCH_NAME_LENGTH] = [0] * PATCH_NAME_LENGTH
        return blanked
    except ValueError:
        pass
    _, data = _extract_tone_data(messages)
    blanked = data.copy()
    blanked[:TONE_NAME_LENGTH] = [0] * TONE_NAME_LENGTH
    return blanked


def calculateFingerprint(messages: List[int]) -> str:
    return hashlib.md5(bytearray(blankedOut(messages))).hexdigest()


# ---------------------------------------------------------------------------
# Parameter grid
#
# Layouts follow the parameter tables in the Owner's Manual (see gr50_params.py at the repository
# root). Offsets are plain byte offsets into the 188-byte patch or the 246-byte tone. Values whose
# meaning the manual leaves unclear are shown as raw numbers rather than guessed.
# ---------------------------------------------------------------------------

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_ACRONYMS = {"wg": "WG", "tvf": "TVF", "tva": "TVA", "lfo": "LFO", "pcm": "PCM", "midi": "MIDI"}


def _raw(v: int) -> str:
    return str(v)


def _plus_one(v: int) -> str:
    return str(v + 1)


def _signed(center: int):
    return lambda v: f"{v - center:+d}" if v != center else "0"


def _labels(*names: str):
    return lambda v: names[v] if 0 <= v < len(names) else str(v)


def _pan(v: int) -> str:
    # 0..14 with 7 in the middle
    return "C" if v == 7 else (f"L{7 - v}" if v < 7 else f"R{v - 7}")


def _note(v: int) -> str:
    return f"{_NOTE_NAMES[v % 12]}{v // 12 - 1}"


def _midi_channel(v: int) -> str:
    return "Off" if v == 16 else str(v + 1)


def _partial_bits(v: int) -> str:
    return " ".join("1" if v & (1 << bit) else "0" for bit in range(4))


_ON_OFF = _labels("off", "on")

# (offset, id, max, formatter)
_PATCH_COMMON = [
    (0x10, "reverb_type", 7, _plus_one),
    (0x11, "reverb_time", 7, _raw),
    (0x12, "reverb_level", 7, _raw),
    (0x13, "velocity_curve", 3, _plus_one),
]
_PATCH_MODE_GROUP = [
    (0x00, "tone_mode", 5, _labels("1st", "2nd", "single", "dual", "velo switch", "mix")),
    (0x01, "tone_mode_sensitivity", 3, _plus_one),
]
_PATCH_TONE_GROUP = [
    (0x00, "tone_group", 3, _labels("a", "b", "i/c", "l")),
    (0x01, "tone_number", 63, _plus_one),
    (0x02, "output_level", 100, _raw),
    (0x03, "panpot", 14, _pan),
    (0x04, "key_shift", 48, _signed(24)),
    (0x05, "fine_tune", 100, _signed(50)),
    (0x06, "chromatic_switch", 1, _ON_OFF),
    (0x08, "reverb_switch", 1, _ON_OFF),
]
_PATCH_EXTERNAL_GENERAL = [
    (0x00, "midi_channel", 16, _midi_channel),
    (0x01, "midi_mode", 1, _labels("poly", "mono")),
    (0x02, "output_level", 100, _raw),
    (0x03, "bender_range", 24, _raw),
]
_PATCH_EXTERNAL_STRING = [
    (0x00, "program_change", 127, _plus_one),
    (0x01, "transpose", 48, _signed(24)),
    (0x02, "string_select", 1, _ON_OFF),
]
_PATCH_INTERNAL_OFFSET = 0x14       # 6 strings x 20 bytes
_PATCH_EXTERNAL_OFFSET = 0x8C       # 2 branches x 24 bytes

_TONE_COMMON = [
    (0x0A, "structure_1_2", 12, _plus_one),
    (0x0B, "structure_3_4", 12, _plus_one),
    (0x0C, "partial_mute", 15, _partial_bits),
    (0x0D, "envelope_mode", 1, _labels("normal", "no sustain")),
]
_TONE_PARTIAL = [
    (0x00, "wg_pitch_coarse", 96, _raw),     # scale unclear: real tones cluster at 24, 36 and 48
    (0x01, "wg_pitch_fine", 100, _signed(50)),
    (0x02, "wg_pitch_key_follow", 16, _raw),
    (0x03, "wg_pitch_bender_switch", 1, _ON_OFF),
    (0x04, "wg_pcm_bank_wave_form", 3, _raw),
    (0x05, "wg_pcm_wave_number", 127, _plus_one),
    (0x06, "wg_pulse_width", 100, _raw),
    (0x07, "wg_pulse_width_velo_sens", 14, _signed(7)),
    (0x08, "pitch_env_depth", 10, _raw),
    (0x09, "pitch_env_velocity", 100, _raw),
    (0x0A, "pitch_env_time_key_follow", 4, _raw),
    (0x0B, "pitch_env_time_1", 100, _raw),
    (0x0C, "pitch_env_time_2", 100, _raw),
    (0x0D, "pitch_env_time_3", 100, _raw),
    (0x0E, "pitch_env_time_4", 100, _raw),
    (0x0F, "pitch_env_level_0", 100, _signed(50)),
    (0x10, "pitch_env_level_1", 100, _signed(50)),
    (0x11, "pitch_env_level_2", 100, _signed(50)),
    (0x12, "pitch_env_sus_level", 100, _signed(50)),
    (0x13, "pitch_env_end_level", 100, _signed(50)),
    (0x14, "pitch_lfo_rate", 100, _raw),
    (0x15, "pitch_lfo_depth", 100, _raw),
    (0x16, "pitch_lfo_mod_sens", 100, _raw),
    (0x17, "tvf_cutoff", 100, _raw),
    (0x18, "tvf_resonance", 30, _raw),
    (0x19, "tvf_key_follow", 14, _raw),
    (0x1A, "tvf_bias_point", 127, _note),
    (0x1B, "tvf_bias_level", 14, _signed(7)),  # real tones use 0..14, centred on 7
    (0x1C, "tvf_env_depth", 100, _raw),
    (0x1D, "tvf_env_velocity", 100, _raw),
    (0x1E, "tvf_env_depth_key_follow", 4, _raw),
    (0x1F, "tvf_env_time_key_follow", 4, _raw),
    (0x20, "tvf_env_time_1", 100, _raw),
    (0x21, "tvf_env_time_2", 100, _raw),
    (0x22, "tvf_env_time_3", 100, _raw),
    (0x23, "tvf_env_time_4", 100, _raw),
    (0x24, "tvf_env_time_5", 100, _raw),
    (0x25, "tvf_env_level_1", 100, _raw),
    (0x26, "tvf_env_level_2", 100, _raw),
    (0x27, "tvf_env_level_3", 100, _raw),
    (0x28, "tvf_env_sus_level", 100, _raw),
    (0x29, "tva_level", 100, _raw),
    (0x2A, "tva_velocity", 100, _raw),
    (0x2B, "tva_bias_point_1", 127, _note),
    (0x2C, "tva_bias_level_1", 12, _raw),    # manual's range and display disagree
    (0x2D, "tva_bias_point_2", 127, _note),
    (0x2E, "tva_bias_level_2", 12, _raw),    # manual's range and display disagree
    (0x2F, "tva_env_time_key_follow", 4, _raw),
    (0x30, "tva_env_time_1_velo", 4, _raw),
    (0x31, "tva_env_time_1", 100, _raw),
    (0x32, "tva_env_time_2", 100, _raw),
    (0x33, "tva_env_time_3", 100, _raw),
    (0x34, "tva_env_time_4", 100, _raw),
    (0x35, "tva_env_time_5", 100, _raw),
    (0x36, "tva_env_level_1", 100, _raw),
    (0x37, "tva_env_level_2", 100, _raw),
    (0x38, "tva_env_level_3", 100, _raw),
    (0x39, "tva_env_sus_level", 100, _raw),
]
_TONE_PARTIAL_OFFSET = 0x0E         # 4 partials x 58 bytes
_TONE_PARTIAL_SIZE = 58


def _label(parameter_id: str) -> str:
    words = [_ACRONYMS.get(word, word) for word in parameter_id.split("_")]
    text = " ".join(words).replace("structure 1 2", "structure 1/2").replace("structure 3 4", "structure 3/4")
    return text[0].upper() + text[1:]


def _decode(data: List[int], base: int, table, group: str, id_prefix: str, name_prefix: str = "") -> List[Dict]:
    result = []
    for offset, parameter_id, max_value, formatter in table:
        value = data[base + offset]
        result.append({
            "id": f"{id_prefix}{parameter_id}",
            "name": f"{name_prefix}{_label(parameter_id)}",
            "group": group,
            "value": value,
            "min": 0,
            "max": max_value,
            "text": formatter(value),
        })
    return result


def _patch_parameters(data: List[int]) -> List[Dict]:
    result = _decode(data, 0, _PATCH_COMMON, "Common", "common.")
    for string in range(6):
        base = _PATCH_INTERNAL_OFFSET + string * 20
        group = f"String {string + 1}"
        prefix = f"string{string + 1}."
        result += _decode(data, base, _PATCH_MODE_GROUP, group, prefix)
        result += _decode(data, base + 0x02, _PATCH_TONE_GROUP, group, prefix + "tone1.", "1st ")
        result += _decode(data, base + 0x0B, _PATCH_TONE_GROUP, group, prefix + "tone2.", "2nd ")
    for branch_index, branch in enumerate("AB"):
        base = _PATCH_EXTERNAL_OFFSET + branch_index * 24
        group = f"External {branch}"
        prefix = f"external{branch}."
        result += _decode(data, base, _PATCH_EXTERNAL_GENERAL, group, prefix)
        for string in range(6):
            result += _decode(data, base + 0x06 + string * 3, _PATCH_EXTERNAL_STRING, group,
                              f"{prefix}string{string + 1}.", f"String {string + 1} ")
    return result


def _tone_parameters(data: List[int]) -> List[Dict]:
    result = _decode(data, 0, _TONE_COMMON, "Common", "common.")
    for partial in range(4):
        base = _TONE_PARTIAL_OFFSET + partial * _TONE_PARTIAL_SIZE
        result += _decode(data, base, _TONE_PARTIAL, f"Partial {partial + 1}", f"partial{partial + 1}.")
    return result


def getPatchParameters(messages: List[int]) -> List[Dict]:
    try:
        _, data = _extract_patch_data(messages)
        return _patch_parameters(data)
    except ValueError:
        pass
    try:
        _, data = _extract_tone_data(messages)
        return _tone_parameters(data)
    except ValueError:
        return []


def make_test_data():
    """Test data for the shared adaptation test suite (test_adaptations.py).

    Fixture: a real bulk dump sent by a GR-50 (64 patches of 188 bytes, 64 user tones of 246 bytes).
    The mock device below answers RQ1 requests from that memory, so the wire-download tests drive
    the real tone handshake (first RQ1 from createProgramDumpRequest, follow-ups from
    isPartOfSingleProgramDump) and check every request against an independently computed list.
    """
    import os
    import knobkraft
    import testing

    fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testData", "Roland_GR50", "GR50_bulk_dump.syx")
    dump = knobkraft.load_sysex(fixture)
    patches, tones = dump[:PATCH_COUNT], dump[PATCH_COUNT:]

    # Independent re-implementation of the request format, so the expected wire traffic doesn't
    # reuse the adaptation's own encoding helpers.
    def rq1(flat_address: int, size: int) -> List[int]:
        body = [(flat_address >> 14) & 0x7F, (flat_address >> 7) & 0x7F, flat_address & 0x7F,
                (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
        return [0xF0, 0x41, 0x10, 0x16, 0x11] + body + [(-sum(body)) & 0x7F, 0xF7]

    def expected_patch_requests() -> List[List[int]]:
        return [rq1((0x51 << 14) + p * 188, 188) for p in range(64)]

    def expected_tone_requests() -> List[List[int]]:
        # Each tone sits in a 256-byte slot; 246 bytes are read as 64 + 64 + 64 + 54
        return [rq1((0x08 << 14) + t * 256 + offset, min(64, 246 - offset))
                for t in range(64) for offset in (0, 64, 128, 192)]

    class GR50MemoryMock:
        """Answers each RQ1 with one DT1 read from the dumped memory, like the real GR-50."""
        def __init__(self, messages: List[List[int]]):
            self.memory = {}
            for message in messages:
                flat = (message[5] << 14) | (message[6] << 7) | message[7]
                for i, value in enumerate(message[8:-2]):
                    self.memory[flat + i] = value

        def respond(self, message: List[int]) -> List[List[int]]:
            assert message[:5] == [0xF0, 0x41, 0x10, 0x16, 0x11], f"Not a GR-50 RQ1: {message}"
            flat = (message[5] << 14) | (message[6] << 7) | message[7]
            size = (message[8] << 14) | (message[9] << 7) | message[10]
            missing = [flat + i for i in range(size) if flat + i not in self.memory]
            assert not missing, f"RQ1 reads outside the dumped memory at {missing[0]:#x}"
            data = [self.memory[flat + i] for i in range(size)]
            body = message[5:8] + data
            return [[0xF0, 0x41, 0x10, 0x16, 0x12] + body + [(-sum(body)) & 0x7F, 0xF7]]

    def programs(_) -> List:
        return [
            testing.ProgramTestData(patches[0], name="Pedal Steel", number=0, friendly_number="I-11"),
            testing.ProgramTestData(patches[1], name="Stereo Acoustic", number=1, friendly_number="I-12"),
            testing.ProgramTestData(patches[63], name="Soft Rhodes", number=63, friendly_number="I-88"),
            # Tones must stay in the tone bank when converted, so give them a tone slot as target
            testing.ProgramTestData(tones[0], name="Akkordeon", number=64, friendly_number="i01", target_no=75),
            testing.ProgramTestData(tones[1], name="Ana-Dig it", number=65, friendly_number="i02", target_no=75),
            testing.ProgramTestData(tones[63], name="Xylophone", number=127, friendly_number="i64", target_no=75),
        ]

    def edit_buffers(_) -> List:
        return [
            testing.ProgramTestData(convertToEditBuffer(0, patches[0]), name="Pedal Steel"),
            testing.ProgramTestData(convertToEditBuffer(0, tones[0]), name="Akkordeon", target_no=75),
        ]

    return testing.TestData(
        sysex=fixture,
        program_generator=programs,
        edit_buffer_generator=edit_buffers,
        program_dump_request=(0, 64, rq1(0x08 << 14, 64)),
        device_detect_call="F0 41 10 16 11 52 00 00 00 00 13 1B F7",
        # Real System Setup reply from a GR-50 set to Unit 1 (device ID 0x10)
        device_detect_reply=("F0 41 10 16 12 52 00 00 40 0F 00 0C 01 01 01 7F 01 00 03 00 04 07 07 07 07 07 07 1F F7", 0),
        expected_patch_count=128,
        mock_device_factory=lambda test_data, adaptation: GR50MemoryMock(dump),
        wire_download_bank=1,
        expected_wire_patch_count=64,
        expected_sent_messages=lambda test_data, adaptation: expected_tone_requests(),
        wire_download_banks=[0, 1],
        expected_multi_bank_patch_count=128,
        expected_multi_bank_sent_messages=lambda test_data, adaptation: expected_patch_requests() + expected_tone_requests(),
    )
