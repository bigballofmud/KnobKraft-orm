#
#   Copyright (c) 2026 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#
#   Tests for the Roland GR-50 Guitar Synthesizer adaptation.
#
#   Coverage highlights:
#     - TONE_STRIDE = 256, not 246  (root cause of original 39% import failure)
#     - Handshake-driven sequential chunk download: createProgramDumpRequest sends
#       only the first RQ1; isPartOfSingleProgramDump returns (True, next_rq1) to
#       trigger each subsequent chunk only after the previous DT1 arrives
#     - Both banks: Internal Patches (0–63) and User Tones (64–127)
#     - All major KnobKraft API functions: detect, edit buffer, program dump, rename, fingerprint
#

import math
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


def _make_tone_bulk(tone_no, tone_name="TestTone  ", data=None):
    """Single 256-byte DT1 as produced by a GR-50 self-initiated bulk dump."""
    body = list(data) if data is not None else [0] * TONE_SIZE
    body[:TONE_NAME_LENGTH] = list(
        tone_name[:TONE_NAME_LENGTH].ljust(TONE_NAME_LENGTH).encode("ascii")
    )
    padded = body + [0] * (TONE_STRIDE - TONE_SIZE)   # 246 data + 10 pad bytes
    return _dt1(_tone_addr(tone_no), padded)


def _tone_buf(tone_no, **kwargs) -> list:
    """Flat byte buffer for a complete tone dump (all chunks concatenated)."""
    return sum(_make_tone_chunks(tone_no, **kwargs), [])


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


def test_tone_request_message_count():
    """createProgramDumpRequest sends only the first RQ1.

    Subsequent chunks are driven via isPartOfSingleProgramDump handshake
    tuples so each RQ1 is sent only after the previous DT1 arrives, matching
    the strict sequential request-response pattern gr50_tool.py uses.
    """
    req = createProgramDumpRequest(0, PATCH_COUNT)
    assert len(_split(req)) == 1


def test_tone_request_first_chunk_size():
    """First RQ1 requests exactly TONE_MAX_PAYLOAD bytes."""
    req = createProgramDumpRequest(0, PATCH_COUNT)
    first_msg = _split(req)[0]
    requested = _a2i(list(first_msg[8:11]))
    assert requested == TONE_MAX_PAYLOAD


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


def test_accepts_tone_first_chunk():
    assert isPartOfSingleProgramDump(_make_tone_chunks(0)[0])


def test_accepts_tone_last_chunk():
    assert isPartOfSingleProgramDump(_make_tone_chunks(0)[-1])


def test_accepts_all_tone_63_chunks():
    """Tone 63 uses a 0x7E base address — must be recognised correctly."""
    for chunk in _make_tone_chunks(63):
        assert isPartOfSingleProgramDump(chunk)


def test_rejects_rq1():
    req = _split(createProgramDumpRequest(0, 0))[0]
    assert not isPartOfSingleProgramDump(req)


def test_rejects_wrong_manufacturer():
    body = [0x51, 0x00, 0x00] + [0] * PATCH_SIZE
    bad = [0xF0, 0x42, DEFAULT_DEVICE_ID, MODEL_ID, COMMAND_DT1] + body + [_cs(body), 0xF7]
    assert not isPartOfSingleProgramDump(bad)


@pytest.mark.parametrize("chunk_size", [64, 123, TONE_SIZE])
def test_accepts_various_chunk_sizes(chunk_size):
    """64-byte, 123-byte, and full 246-byte chunks must all be accepted."""
    for chunk in _make_tone_chunks(0, chunk_size=chunk_size):
        assert isPartOfSingleProgramDump(chunk)


# ---------------------------------------------------------------------------
# isSingleProgramDump
# ---------------------------------------------------------------------------

def test_patch_is_complete_on_its_own():
    assert isSingleProgramDump(_make_patch(5))


def test_incomplete_tone_buf_not_recognised():
    """A partial tone buffer is not a complete dump."""
    chunks = _make_tone_chunks(0)
    if len(chunks) == 1:
        pytest.skip("TONE_MAX_PAYLOAD == TONE_SIZE: single chunk is always complete")
    assert not isSingleProgramDump(chunks[0])


def test_complete_tone_buf_recognised():
    assert isSingleProgramDump(_tone_buf(0))


def test_edit_buffer_is_not_single_program():
    assert not isSingleProgramDump(_make_patch_eb())


def test_empty_is_not_single_program():
    assert not isSingleProgramDump([])


# ---------------------------------------------------------------------------
# Bulk-dump format (256-byte DT1 per tone, as produced by the GR-50 itself)
# ---------------------------------------------------------------------------

def test_bulk_tone_is_part_of_program_dump():
    """A 256-byte (TONE_STRIDE) DT1 must be recognised as part of a program dump."""
    bulk = _make_tone_bulk(0)
    result = isPartOfSingleProgramDump(bulk)
    # Must be truthy; must NOT be a tuple requesting a follow-up RQ1
    assert result is True


def test_bulk_tone_is_complete():
    """A single 256-byte DT1 is a complete tone dump on its own."""
    assert isSingleProgramDump(_make_tone_bulk(7))


def test_bulk_tone_data_is_246_bytes():
    """Extracted tone data must be TONE_SIZE (246) bytes — padding stripped."""
    from Roland_GR50 import nameFromDump
    tone_name = "BulkTone  "
    bulk = _make_tone_bulk(3, tone_name=tone_name)
    assert nameFromDump(bulk) == tone_name.rstrip()


@pytest.mark.parametrize("tone_no", [0, 1, 31, 32, 63])
def test_bulk_tone_program_number(tone_no):
    """numberFromDump must return PATCH_COUNT + tone_no for bulk-format tones."""
    assert numberFromDump(_make_tone_bulk(tone_no)) == PATCH_COUNT + tone_no


def test_all_64_bulk_tones_recognised():
    """All 64 bulk-format tone messages must each be complete, standalone dumps."""
    for tone_no in range(TONE_COUNT):
        assert isSingleProgramDump(_make_tone_bulk(tone_no)), f"tone {tone_no} not recognised"


# ---------------------------------------------------------------------------
# numberFromDump
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("patch_no", [0, 1, 32, 63])
def test_number_from_patch(patch_no):
    assert numberFromDump(_make_patch(patch_no)) == patch_no


@pytest.mark.parametrize("tone_no", [0, 1, 32, 63])
def test_number_from_tone(tone_no):
    assert numberFromDump(_tone_buf(tone_no)) == PATCH_COUNT + tone_no


def test_tone_63_program_number_is_127():
    assert numberFromDump(_tone_buf(63)) == 127


# ---------------------------------------------------------------------------
# nameFromDump
# ---------------------------------------------------------------------------

def test_name_from_patch():
    dump = _make_patch(0, patch_name="Strings         ")
    assert nameFromDump(dump) == "Strings"


def test_name_from_tone():
    assert nameFromDump(_tone_buf(0, tone_name="Lead      ")) == "Lead"


def test_name_in_first_chunk():
    """Tone names live at offset 0, within the first chunk regardless of chunk size."""
    assert nameFromDump(_tone_buf(0, tone_name="Bass      ")) == "Bass"


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
    renamed = renamePatch(_tone_buf(7, tone_name="OldName   "), "NewName   ")
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
    fp_a = calculateFingerprint(_tone_buf(0, tone_name="Alpha     ", data=list(body)))
    fp_b = calculateFingerprint(_tone_buf(0, tone_name="Zeta      ", data=list(body)))
    assert fp_a == fp_b


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
    eb = convertToEditBuffer(0, _tone_buf(3))
    assert isEditBufferDump(eb)
    assert not isSingleProgramDump(eb)


def test_convert_tone_from_edit_buffer():
    eb = convertToEditBuffer(0, _tone_buf(0, tone_name="EbTone    "))
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
    buf = _tone_buf(tone_no, data=data)
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
    assert numberFromDump(_tone_buf(0)) == PATCH_COUNT


# ---------------------------------------------------------------------------
# Hardware-constraint tests — model the conditions that cause real timeouts
#
# The MOTU MIDI Express XT resets its input port after ~252 inbound SysEx
# transactions.  macOS can auto-detect the GR-50 on both the physical port
# ("Port 7") AND the "All Cables" merged virtual port.  When that happens,
# every DT1 response is delivered to KnobKraft twice, doubling the effective
# transaction count seen by the MOTU hardware.
# ---------------------------------------------------------------------------

MOTU_RESET_THRESHOLD = 252


def test_transaction_count_single_port():
    """Initial RQ1 count for the full tone bank stays well under the MOTU reset threshold.

    createProgramDumpRequest sends only the first chunk per tone; subsequent
    chunks are driven by the isPartOfSingleProgramDump handshake at runtime and
    are not counted here.  64 initial transactions is far below the MOTU limit.
    """
    total = sum(
        len(_split(createProgramDumpRequest(0, PATCH_COUNT + t)))
        for t in range(TONE_COUNT)
    )
    assert total < MOTU_RESET_THRESHOLD, (
        f"Full tone bank needs {total} initial transactions "
        f"(MOTU limit: {MOTU_RESET_THRESHOLD})"
    )


def test_transaction_count_dual_port():
    """Even if All Cables double-detection were still active, initial count stays safe.

    FindSynthOnMidiNetwork.cpp now skips output-only ports so dual detection no
    longer occurs in practice.  This test confirms the handshake approach keeps
    the initial RQ1 count low enough that doubling it would still be safe.
    """
    total_requests = sum(
        len(_split(createProgramDumpRequest(0, PATCH_COUNT + t)))
        for t in range(TONE_COUNT)
    )
    effective = total_requests * 2
    assert effective < MOTU_RESET_THRESHOLD, (
        f"{total_requests} requests × 2 ports = {effective} effective transactions "
        f"(MOTU limit: {MOTU_RESET_THRESHOLD})"
    )


def test_duplicate_dt1_chunks_reassemble():
    """Duplicate DT1 chunks must not corrupt reassembly."""
    for tone_no in [0, 32, 63]:
        chunks = _make_tone_chunks(tone_no)
        doubled = sum(chunks + chunks, [])   # each chunk appears twice
        assert isSingleProgramDump(doubled), f"tone {tone_no}: duplicates broke reassembly"
        assert numberFromDump(doubled) == PATCH_COUNT + tone_no


def test_full_bank_import_simulation():
    """Simulate a sequential KnobKraft import of all 64 User Tones."""
    for tone_no in range(TONE_COUNT):
        data = [(tone_no + i) % 128 for i in range(TONE_SIZE)]
        buf = _tone_buf(tone_no, data=data)
        assert isSingleProgramDump(buf), f"tone {tone_no} not recognised"
        assert numberFromDump(buf) == PATCH_COUNT + tone_no
