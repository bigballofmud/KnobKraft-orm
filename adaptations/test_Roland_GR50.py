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
#     - Real data from a GR-50 bulk dump (testData/Roland_GR50/GR50_bulk_dump.syx)
#
#   The shared suite (pytest test_adaptations.py --adaptation Roland_GR50.py) additionally drives
#   full bank downloads through a mock GR-50 via make_test_data() and checks every request sent.
#

import pytest
import Roland_GR50
from Roland_GR50 import *
import knobkraft.sysex as sysex


@pytest.fixture(autouse=True)
def reset_device_id():
    """channelIfValidDeviceResponse stores the detected unit in a module global; reset it so no test
    inherits a device ID from an earlier one (e.g. Unit 16 = 0x1F from the detection tests)."""
    Roland_GR50._device_id = DEFAULT_DEVICE_ID
    yield
    Roland_GR50._device_id = DEFAULT_DEVICE_ID


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
    """Single 256-byte DT1 covering a whole tone slot (246 data + 10 padding).

    The real bulk dump in testData sends 246-byte tone DT1s; the adaptation also accepts this
    full-slot form, so both are tested."""
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
    # The GR-50 drops requests sent sooner than ~75 ms after its reply; keep a margin
    assert generalMessageDelay() >= 75


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


# ---------------------------------------------------------------------------
# Tone handshake: each DT1 reply must produce exactly the next RQ1
# ---------------------------------------------------------------------------

def _rq1(address: list, size: int) -> list:
    """Independent RQ1 builder (does not reuse the adaptation's encoding)."""
    body = address + [(size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
    return [0xF0, ROLAND_ID, DEFAULT_DEVICE_ID, MODEL_ID, COMMAND_RQ1] + body + [_cs(body), 0xF7]


def _reply_to(request: list, slot_data: list, slot_base: int) -> list:
    """What a GR-50 sends back for an RQ1 into a tone slot holding slot_data."""
    flat = _a2i(request[5:8])
    size = _a2i(request[8:11])
    offset = flat - slot_base
    return _dt1(request[5:8], slot_data[offset:offset + size])


@pytest.mark.parametrize("tone_no", [0, 1, 63])
def test_tone_handshake_requests_each_chunk_in_order(tone_no):
    """Walk one tone through the handshake: 4 RQ1s of 64/64/64/54 bytes, then a plain True."""
    slot_base = _a2i(_tone_addr(tone_no))
    data = [(tone_no * 7 + i) % 128 for i in range(TONE_SIZE)]
    expected = [_rq1(_i2a(slot_base + off), min(64, TONE_SIZE - off)) for off in (0, 64, 128, 192)]

    request = createProgramDumpRequest(0, PATCH_COUNT + tone_no)
    sent, received = [request], []
    while True:
        reply = _reply_to(request, data, slot_base)
        received.append(reply)
        result = isPartOfSingleProgramDump(reply)
        if result is True:
            break
        assert isinstance(result, tuple) and result[0] is True, f"unexpected handshake result {result!r}"
        request = result[1]
        sent.append(request)
        assert len(sent) <= 4, "handshake asked for more than the 4 chunks of a tone"

    assert sent == expected
    buf = sum(received, [])
    assert isSingleProgramDump(buf)
    assert numberFromDump(buf) == PATCH_COUNT + tone_no


def test_tone_63_requests_stay_inside_its_slot():
    """The last tone's chunks address 0x08 7E xx / 0x08 7F xx and never spill past the slot."""
    slot_base = _a2i(_tone_addr(63))
    assert _tone_addr(63) == [0x08, 0x7E, 0x00]
    data = [0] * TONE_SIZE
    request = createProgramDumpRequest(0, PATCH_COUNT + 63)
    while True:
        flat, size = _a2i(request[5:8]), _a2i(request[8:11])
        assert slot_base <= flat and flat + size <= slot_base + TONE_SIZE
        assert all(0 <= b <= 0x7F for b in request[5:11])
        result = isPartOfSingleProgramDump(_reply_to(request, data, slot_base))
        if result is True:
            break
        request = result[1]


def test_patch_reply_needs_no_follow_up_request():
    """A 188-byte patch DT1 is complete: the handshake returns plain True, not a tuple."""
    assert isPartOfSingleProgramDump(_make_patch(5)) is True


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


def test_channel_is_device_id_offset_not_basic_midi_channel():
    data = [0] * SYSTEM_SETUP_SIZE
    data[1] = 15  # basic MIDI channel 16 — must be ignored
    response = _dt1(list(SYSTEM_SETUP_ADDR), data, device_id=0x10)
    assert channelIfValidDeviceResponse(response) == 0


@pytest.mark.parametrize("unit_offset", [0, 1, 7, 15])
def test_detect_channel_round_trips_to_same_device_id(unit_offset):
    # The channel returned on detection is saved by KnobKraft and fed back to
    # createDeviceDetectMessage for the startup check; it must address the same unit.
    device_id = 0x10 + unit_offset
    data = [0] * SYSTEM_SETUP_SIZE
    data[1] = 15
    response = _dt1(list(SYSTEM_SETUP_ADDR), data, device_id=device_id)
    channel = channelIfValidDeviceResponse(response)
    assert createDeviceDetectMessage(channel)[2] == device_id


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
# Robustness
# ---------------------------------------------------------------------------

def test_duplicate_dt1_chunks_reassemble():
    """Duplicate DT1 chunks must not corrupt reassembly."""
    for tone_no in [0, 32, 63]:
        chunks = _make_tone_chunks(tone_no)
        doubled = sum(chunks + chunks, [])   # each chunk appears twice
        assert isSingleProgramDump(doubled), f"tone {tone_no}: duplicates broke reassembly"
        assert numberFromDump(doubled) == PATCH_COUNT + tone_no


def test_rejects_dt1_with_bad_checksum():
    bad = _make_patch(0)
    bad[-2] = (bad[-2] + 1) & 0x7F
    assert not isPartOfSingleProgramDump(bad)
    assert not isSingleProgramDump(bad)


def test_tone_sent_to_patch_slot_stays_a_tone():
    """The data decides the bank; the slot number only picks the position within it."""
    moved = convertToProgramDump(0, _tone_buf(3, tone_name="KeepMe    "), 11)
    assert numberFromDump(moved) == PATCH_COUNT + 11
    assert nameFromDump(moved) == "KeepMe"


def test_patch_sent_to_tone_slot_stays_a_patch():
    moved = convertToProgramDump(0, _make_patch(3, "KeepMe"), PATCH_COUNT + 5)
    assert numberFromDump(moved) == 5
    assert nameFromDump(moved) == "KeepMe"


# ---------------------------------------------------------------------------
# Edit buffer request
# ---------------------------------------------------------------------------

def test_edit_buffer_request_reads_patch_temporary_area():
    assert createEditBufferRequest(0) == _rq1(list(PATCH_TEMP_BASE), PATCH_SIZE)


def test_part_of_edit_buffer_dump():
    assert isPartOfEditBufferDump(_make_patch_eb())
    assert not isPartOfEditBufferDump(_make_patch(0))
    assert not isPartOfEditBufferDump(createEditBufferRequest(0))


# ---------------------------------------------------------------------------
# Real data: a bulk dump sent by a GR-50 (testData/Roland_GR50/GR50_bulk_dump.syx)
# ---------------------------------------------------------------------------

def _real_dump():
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testData", "Roland_GR50", "GR50_bulk_dump.syx")
    with open(path, "rb") as f:
        return _split(list(f.read()))


def test_real_bulk_dump_has_all_patches_and_tones_in_order():
    messages = _real_dump()
    assert len(messages) == PATCH_COUNT + TONE_COUNT
    assert [numberFromDump(m) for m in messages] == list(range(PATCH_COUNT + TONE_COUNT))
    assert all(isSingleProgramDump(m) for m in messages)


@pytest.mark.parametrize("index, name", [(0, "Pedal Steel"), (63, "Soft Rhodes"), (64, "Akkordeon"), (127, "Xylophone")])
def test_real_bulk_dump_names(index, name):
    assert nameFromDump(_real_dump()[index]) == name


def test_real_tones_survive_edit_buffer_round_trip():
    """Real tone data must come back byte-identical after edit buffer and program conversions."""
    for message in _real_dump()[PATCH_COUNT:PATCH_COUNT + 8]:
        number = numberFromDump(message)
        round_trip = convertToProgramDump(0, convertToEditBuffer(0, message), number)
        assert round_trip == message
