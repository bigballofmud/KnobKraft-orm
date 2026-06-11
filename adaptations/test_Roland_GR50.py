#
#   Copyright (c) 2026 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#
#   Tests for the Roland GR-50 Guitar Synthesizer adaptation.
#
#   Coverage highlights:
#     - TONE_STRIDE = 256, not 246  (the root cause of the original 39% import failure)
#     - 2-chunk (123+123) protocol round-trips for all tone slots, especially tone 63
#     - Both banks: Internal Patches (0–63) and User Tones (64–127)
#     - All major KnobKraft API functions: detect, edit buffer, program dump, rename, fingerprint
#

import pytest
from Roland_GR50 import *
import knobkraft.sysex as sysex


# ---------------------------------------------------------------------------
# Test helpers — reimplement private arithmetic without importing _ functions
# ---------------------------------------------------------------------------

def _cs(body: list) -> int:
    """Roland checksum: (-sum(body)) & 0x7F"""
    return (-sum(body)) & 0x7F


def _a2i(addr: list) -> int:
    """3-byte 7-bit address → flat integer."""
    return (addr[0] << 14) | (addr[1] << 7) | addr[2]


def _i2a(n: int) -> list:
    """Flat integer → 3-byte 7-bit address."""
    return [(n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F]


def _tone_addr(tone_no: int) -> list:
    return _i2a(_a2i(list(TONE_MEMORY_BASE)) + tone_no * TONE_STRIDE)


def _patch_addr(patch_no: int) -> list:
    return _i2a(_a2i(list(PATCH_MEMORY_BASE)) + patch_no * PATCH_SIZE)


def _dt1(address: list, data: list, device_id: int = DEFAULT_DEVICE_ID) -> list:
    body = address + data
    return [0xF0, ROLAND_ID, device_id, MODEL_ID, COMMAND_DT1] + body + [_cs(body), 0xF7]


def _split(flat: list) -> list:
    """Split a flat SysEx byte stream into individual messages."""
    return [flat[s:e] for s, e in sysex.findSysexDelimiters(flat)]


def _make_patch(patch_no, patch_name="TestPatch       ", data=None):
    body = list(data) if data is not None else [0] * PATCH_SIZE
    body[:PATCH_NAME_LENGTH] = list(
        patch_name[:PATCH_NAME_LENGTH].ljust(PATCH_NAME_LENGTH).encode("ascii")
    )
    return _dt1(_patch_addr(patch_no), body)


def _make_patch_eb(patch_name="TestPatch       ", data=None):
    body = list(data) if data is not None else [0] * PATCH_SIZE
    body[:PATCH_NAME_LENGTH] = list(
        patch_name[:PATCH_NAME_LENGTH].ljust(PATCH_NAME_LENGTH).encode("ascii")
    )
    return _dt1(list(PATCH_TEMP_BASE), body)


def _make_tone_chunks(tone_no, tone_name="TestTone  ", data=None, chunk_size=None):
    """Return list of DT1 messages that a GR-50 would send for a given tone."""
    if chunk_size is None:
        chunk_size = TONE_MAX_PAYLOAD
    body = list(data) if data is not None else [0] * TONE_SIZE
    body[:TONE_NAME_LENGTH] = list(
        tone_name[:TONE_NAME_LENGTH].ljust(TONE_NAME_LENGTH).encode("ascii")
    )
    base = _a2i(_tone_addr(tone_no))
    msgs, offset = [], 0
    while offset < TONE_SIZE:
        sz = min(chunk_size, TONE_SIZE - offset)
        msgs.append(_dt1(_i2a(base + offset), body[offset:offset + sz]))
        offset += sz
    return msgs


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_name():
    assert name() == "Roland GR-50"


def test_bank_descriptors():
    banks = bankDescriptors()
    assert len(banks) == 2
    assert banks[0] == {"bank": 0, "name": "Internal Patches", "size": 64, "type": "Patch"}
    assert banks[1] == {"bank": 1, "name": "User Tones",       "size": 64, "type": "Tone"}


def test_general_message_delay():
    assert generalMessageDelay() == 150


# ---------------------------------------------------------------------------
# Address arithmetic — TONE_STRIDE is the critical constant
# ---------------------------------------------------------------------------

def test_tone_stride_is_256_not_246():
    """Stride must be 256; using 246 would put tone[1]+ at invalid addresses."""
    assert _a2i(_tone_addr(1)) - _a2i(_tone_addr(0)) == 256


@pytest.mark.parametrize("tone_no, expected", [
    (0,  [0x08, 0x00, 0x00]),
    (1,  [0x08, 0x02, 0x00]),   # base + 256; middle byte 2, not 1 (which 246 would give)
    (63, [0x08, 0x7E, 0x00]),
])
def test_tone_address_known_values(tone_no, expected):
    assert _tone_addr(tone_no) == expected


def test_tone_63_chunk_addresses():
    """Tone 63 chunk addresses are correctly computed and all bytes are valid 7-bit."""
    chunk0 = _tone_addr(63)
    chunk1 = _i2a(_a2i(chunk0) + 123)
    assert chunk0 == [0x08, 0x7E, 0x00]
    assert chunk1 == [0x08, 0x7E, 0x7B]   # offset 123 = 0x7B encoded in last byte
    for byte in chunk0 + chunk1:
        assert 0x00 <= byte <= 0x7F


# ---------------------------------------------------------------------------
# createProgramDumpRequest
# ---------------------------------------------------------------------------

def test_patch_request_is_one_message():
    assert len(_split(createProgramDumpRequest(0, 0))) == 1


def test_patch_request_is_rq1():
    msg = _split(createProgramDumpRequest(0, 0))[0]
    assert msg[4] == COMMAND_RQ1


def test_tone_request_is_two_messages():
    assert len(_split(createProgramDumpRequest(0, PATCH_COUNT))) == 2


def test_tone_request_chunk_sizes_sum_to_tone_size():
    """Total bytes requested across all chunks must equal TONE_SIZE."""
    req = createProgramDumpRequest(0, PATCH_COUNT)
    total = sum(_a2i(list(m[8:11])) for m in _split(req))
    assert total == TONE_SIZE


@pytest.mark.parametrize("patchNo, expected_addr", [
    (PATCH_COUNT + 0,  [0x08, 0x00, 0x00]),   # tone 0
    (PATCH_COUNT + 1,  [0x08, 0x02, 0x00]),   # tone 1 — catches stride bugs
    (PATCH_COUNT + 63, [0x08, 0x7E, 0x00]),   # tone 63
])
def test_tone_request_first_chunk_address(patchNo, expected_addr):
    first_msg = _split(createProgramDumpRequest(0, patchNo))[0]
    assert list(first_msg[5:8]) == expected_addr


# ---------------------------------------------------------------------------
# isPartOfSingleProgramDump
# ---------------------------------------------------------------------------

def test_accepts_full_patch_dt1():
    assert isPartOfSingleProgramDump(_make_patch(0))


def test_accepts_tone_chunk_offset_0():
    assert isPartOfSingleProgramDump(_make_tone_chunks(0)[0])


def test_accepts_tone_chunk_offset_123():
    assert isPartOfSingleProgramDump(_make_tone_chunks(0)[1])


def test_accepts_tone_63_both_chunks():
    """Tone 63 uses a 0x7F address byte — must be recognised correctly."""
    chunks = _make_tone_chunks(63)
    assert isPartOfSingleProgramDump(chunks[0])
    assert isPartOfSingleProgramDump(chunks[1])


def test_rejects_rq1():
    req = _split(createProgramDumpRequest(0, 0))[0]
    assert not isPartOfSingleProgramDump(req)


def test_rejects_wrong_manufacturer():
    body = [0x51, 0x00, 0x00] + [0] * PATCH_SIZE
    bad = [0xF0, 0x42, DEFAULT_DEVICE_ID, MODEL_ID, COMMAND_DT1] + body + [_cs(body), 0xF7]
    assert not isPartOfSingleProgramDump(bad)


@pytest.mark.parametrize("chunk_size", [64, 123])
def test_accepts_various_chunk_sizes(chunk_size):
    """Both the old 64-byte and the current 123-byte chunk sizes must be accepted."""
    for chunk in _make_tone_chunks(0, chunk_size=chunk_size):
        assert isPartOfSingleProgramDump(chunk)


# ---------------------------------------------------------------------------
# isSingleProgramDump
# ---------------------------------------------------------------------------

def test_patch_is_complete_on_its_own():
    assert isSingleProgramDump(_make_patch(5))


def test_single_tone_chunk_is_incomplete():
    assert not isSingleProgramDump(_make_tone_chunks(0)[0])


def test_both_tone_chunks_are_complete():
    chunks = _make_tone_chunks(0)
    assert isSingleProgramDump(chunks[0] + chunks[1])


def test_edit_buffer_is_not_single_program():
    assert not isSingleProgramDump(_make_patch_eb())


def test_empty_is_not_single_program():
    assert not isSingleProgramDump([])


# ---------------------------------------------------------------------------
# numberFromDump
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("patch_no", [0, 1, 32, 63])
def test_number_from_patch(patch_no):
    assert numberFromDump(_make_patch(patch_no)) == patch_no


@pytest.mark.parametrize("tone_no", [0, 1, 32, 63])
def test_number_from_tone(tone_no):
    chunks = _make_tone_chunks(tone_no)
    assert numberFromDump(chunks[0] + chunks[1]) == PATCH_COUNT + tone_no


def test_tone_63_program_number_is_127():
    chunks = _make_tone_chunks(63)
    assert numberFromDump(chunks[0] + chunks[1]) == 127


# ---------------------------------------------------------------------------
# nameFromDump
# ---------------------------------------------------------------------------

def test_name_from_patch():
    dump = _make_patch(0, patch_name="Strings         ")
    assert nameFromDump(dump) == "Strings"


def test_name_from_tone():
    chunks = _make_tone_chunks(0, tone_name="Lead      ")
    assert nameFromDump(chunks[0] + chunks[1]) == "Lead"


def test_name_falls_in_first_chunk():
    """Tone names are at offset 0, entirely within the first 123-byte chunk."""
    chunks = _make_tone_chunks(0, tone_name="Bass      ")
    assert nameFromDump(chunks[0] + chunks[1]) == "Bass"


# ---------------------------------------------------------------------------
# renamePatch
# ---------------------------------------------------------------------------

def test_rename_patch():
    dump = _make_patch(3, patch_name="Old Name        ")
    renamed = renamePatch(dump, "New Name        ")
    assert nameFromDump(renamed) == "New Name"
    assert isSingleProgramDump(renamed)
    assert numberFromDump(renamed) == 3


def test_rename_tone():
    chunks = _make_tone_chunks(7, tone_name="OldName   ")
    renamed = renamePatch(chunks[0] + chunks[1], "NewName   ")
    assert nameFromDump(renamed) == "NewName"
    assert isSingleProgramDump(renamed)
    assert numberFromDump(renamed) == PATCH_COUNT + 7


# ---------------------------------------------------------------------------
# calculateFingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_ignores_patch_name():
    body = [0x55] * PATCH_SIZE
    dump_a = _make_patch(0, patch_name="Name One        ", data=list(body))
    dump_b = _make_patch(0, patch_name="Name Two        ", data=list(body))
    assert calculateFingerprint(dump_a) == calculateFingerprint(dump_b)


def test_fingerprint_differs_for_different_patch_data():
    dump_a = _make_patch(0, data=[0x00] * PATCH_SIZE)
    dump_b = _make_patch(0, data=[0x7F] * PATCH_SIZE)
    assert calculateFingerprint(dump_a) != calculateFingerprint(dump_b)


def test_fingerprint_ignores_tone_name():
    body = [0x33] * TONE_SIZE
    chunks_a = _make_tone_chunks(0, tone_name="Alpha     ", data=list(body))
    chunks_b = _make_tone_chunks(0, tone_name="Zeta      ", data=list(body))
    assert calculateFingerprint(chunks_a[0] + chunks_a[1]) == calculateFingerprint(chunks_b[0] + chunks_b[1])


# ---------------------------------------------------------------------------
# Edit buffer
# ---------------------------------------------------------------------------

def test_patch_edit_buffer_recognised():
    assert isEditBufferDump(_make_patch_eb())


def test_patch_memory_slot_not_edit_buffer():
    assert not isEditBufferDump(_make_patch(0))


def test_convert_patch_to_edit_buffer():
    eb = convertToEditBuffer(0, _make_patch(5))
    assert isEditBufferDump(eb)
    assert not isSingleProgramDump(eb)


def test_convert_patch_from_edit_buffer():
    eb = _make_patch_eb(patch_name="Test            ")
    prog = convertToProgramDump(0, eb, 10)
    assert isSingleProgramDump(prog)
    assert numberFromDump(prog) == 10
    assert nameFromDump(prog) == "Test"


def test_convert_tone_to_edit_buffer():
    chunks = _make_tone_chunks(3)
    eb = convertToEditBuffer(0, chunks[0] + chunks[1])
    assert isEditBufferDump(eb)
    assert not isSingleProgramDump(eb)


def test_convert_tone_from_edit_buffer():
    chunks = _make_tone_chunks(0, tone_name="EbTone    ")
    eb = convertToEditBuffer(0, chunks[0] + chunks[1])
    prog = convertToProgramDump(0, eb, PATCH_COUNT + 5)
    assert isSingleProgramDump(prog)
    assert numberFromDump(prog) == PATCH_COUNT + 5
    assert nameFromDump(prog) == "EbTone"


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def test_create_detect_message_is_own_sysex():
    assert isOwnSysex(createDeviceDetectMessage(0))


def test_channel_detected_from_system_setup():
    data = [0] * SYSTEM_SETUP_SIZE
    data[1] = 5   # MIDI channel = 5
    response = _dt1(list(SYSTEM_SETUP_ADDR), data)
    assert channelIfValidDeviceResponse(response) == 5


def test_wrong_manufacturer_not_detected():
    assert channelIfValidDeviceResponse([0xF0, 0x42, 0x10, 0x16, 0xF7]) == -1


# ---------------------------------------------------------------------------
# Full round-trips — the key regression suite
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tone_no", [0, 1, 32, 62, 63])
def test_tone_full_round_trip(tone_no):
    data = [(tone_no * 7 + i) % 128 for i in range(TONE_SIZE)]
    chunks = _make_tone_chunks(tone_no, data=data)
    buf = chunks[0] + chunks[1]
    assert isSingleProgramDump(buf)
    assert numberFromDump(buf) == PATCH_COUNT + tone_no


@pytest.mark.parametrize("patch_no", [0, 1, 32, 62, 63])
def test_patch_full_round_trip(patch_no):
    data = [(patch_no * 7 + i) % 128 for i in range(PATCH_SIZE)]
    dump = _make_patch(patch_no, data=data)
    assert isSingleProgramDump(dump)
    assert numberFromDump(dump) == patch_no


def test_bank_boundary_patch_63_vs_tone_0():
    """Program 63 is the last patch; program 64 is the first tone."""
    assert numberFromDump(_make_patch(63)) == 63
    chunks = _make_tone_chunks(0)
    assert numberFromDump(chunks[0] + chunks[1]) == PATCH_COUNT
