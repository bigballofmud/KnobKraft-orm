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
TONE_MAX_PAYLOAD   = TONE_SIZE  # single 246-byte request per tone; 64 requests × 2 ports = 128 transactions,
                                # well under MOTU MIDI Express XT reset threshold (~252)

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
            if offset + len(data) <= TONE_SIZE:
                slots.setdefault(slot, {})[offset] = data

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
    return 150


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
        if len(data) >= 2 and 0 <= data[1] <= 15:
            return data[1]
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
        result: List[int] = []
        offset = 0
        while offset < TONE_SIZE:
            chunk = min(TONE_MAX_PAYLOAD, TONE_SIZE - offset)
            result += _build_message(_device_id, COMMAND_RQ1,
                                     _int_to_addr(base_flat + offset),
                                     _size_as_7bit(chunk))
            offset += chunk
        return result
    return _build_message(_device_id, COMMAND_RQ1, _patch_address(patchNo), _size_as_7bit(PATCH_SIZE))


def isPartOfSingleProgramDump(message: List[int]) -> bool:
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
    delta = _addr_to_int(address) - tone_base_flat
    if 0 <= delta < TONE_COUNT * TONE_STRIDE:
        offset_in_slot = delta % TONE_STRIDE
        if offset_in_slot + len(data) <= TONE_SIZE:
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
    if program_number >= PATCH_COUNT:
        tone_no = (program_number - PATCH_COUNT) % TONE_COUNT
        _, data = _extract_tone_data(messages)
        return _build_message(_device_id, COMMAND_DT1, _tone_address(tone_no), data)
    _, data = _extract_patch_data(messages)
    return _build_message(_device_id, COMMAND_DT1, _patch_address(program_number), data)


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
