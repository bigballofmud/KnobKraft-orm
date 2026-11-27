#
#   Copyright (c) 2026 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#
#   Tests for the Roland D-50 parameter grid (getPatchParameters / setPatchParameters).
#
#   The parameter map follows the D-50 MIDI Implementation, tables *4-4 to *4-6. The real bank in
#   testData/Roland_D50 checks the offsets: every value of all 64 patches must lie in the manual's range.
#

import pytest

import knobkraft
import RolandD50 as d50


@pytest.fixture(scope="module")
def patches():
    messages = knobkraft.load_sysex("testData/Roland_D50/Roland_D50_DIGITAL DREAMS.syx", as_single_list=False)
    dump = [m for m in messages if d50.isPartOfBankDump(m)]
    result = d50.extractPatchesFromAllBankMessages(dump)
    assert len(result) == 64
    return result


def by_id(parameters):
    return {p["id"]: p for p in parameters}


def block_data(messages):
    positions = knobkraft.sysex.findSysexDelimiters(messages, 7)
    return [d50.d_50.parseRolandMessage(messages[start:end])[2] for start, end in positions]


def test_every_value_of_a_real_bank_is_in_range(patches):
    for number, patch in enumerate(patches):
        parameters = d50.getPatchParameters(patch)
        assert len(parameters) == 314
        for p in parameters:
            assert p["min"] <= p["value"] <= p["max"], (number, p["id"], p["value"])


def test_sections_come_in_grid_order(patches):
    groups = []
    for p in d50.getPatchParameters(patches[0]):
        if p["group"] not in groups:
            groups.append(p["group"])
    assert groups == ["Patch", "Upper common", "Upper partial 1", "Upper partial 2",
                      "Lower common", "Lower partial 1", "Lower partial 2"]
    ids = [p["id"] for p in d50.getPatchParameters(patches[0])]
    assert len(ids) == len(set(ids))


def test_values_are_read_from_the_right_bytes(patches):
    patch = patches[0]
    blocks = block_data(patch)
    values = by_id(d50.getPatchParameters(patch))
    # Patch block (#6): key mode at 18, reverb type at 30
    assert values["patch.key_mode"]["value"] == blocks[6][18]
    assert values["patch.reverb_type"]["value"] == blocks[6][30]
    # Upper common (#2) and lower common (#5): structure at 10, partial balance at 47
    assert values["upper.common.structure"]["value"] == blocks[2][10]
    assert values["lower.common.partial_balance"]["value"] == blocks[5][47]
    # Partials: upper 1 is block 0, lower 2 is block 4; PCM wave at 7, TVA after touch range at 53
    assert values["upper.partial1.wg_pcm_wave_no"]["value"] == blocks[0][7]
    assert values["lower.partial2.tva_mod_aftertouch_range"]["value"] == blocks[4][53]


def test_value_texts_follow_the_manual():
    assert d50._note(0)(0) == "C1" and d50._note(0)(1) == "C#1" and d50._note(0)(72) == "C7"
    assert d50._note(12)(0) == "C2" and d50._note(12)(60) == "C7"  # Split point
    assert d50._bias_point(0) == "<A1" and d50._bias_point(63) == "<C7"
    assert d50._bias_point(64) == ">A1" and d50._bias_point(127) == ">C7"
    assert d50._PLUS_MINUS_50(0) == "-50" and d50._PLUS_MINUS_50(50) == "0" and d50._PLUS_MINUS_50(100) == "+50"
    assert d50._offset(12)(0) == "-12" and d50._offset(12)(12) == "0"  # TVA bias level: -12 to 0
    assert len(d50._KEYFOLLOW_PITCH.options) == 17
    assert len(d50._KEYFOLLOW_TVF.options) == 15
    parameters = by_id(d50.getPatchParameters(d50.d_50.convertToEditBuffer(0, _first_patch())))
    assert len(parameters["upper.common.low_eq_frequency"]["options"]) == 16
    assert len(parameters["upper.common.high_eq_frequency"]["options"]) == 22
    assert len(parameters["upper.common.high_eq_q"]["options"]) == 9
    assert len(parameters["patch.key_mode"]["options"]) == 9


def _first_patch():
    messages = knobkraft.load_sysex("testData/Roland_D50/Roland_D50_DIGITAL DREAMS.syx", as_single_list=False)
    return d50.extractPatchesFromAllBankMessages([m for m in messages if d50.isPartOfBankDump(m)])[0]


@pytest.mark.parametrize("kind", ["program", "edit buffer"])
def test_setting_a_value_changes_only_that_byte(patches, kind):
    original = patches[5] if kind == "program" else d50.d_50.convertToEditBuffer(0, patches[5])
    before = by_id(d50.getPatchParameters(original))
    target = "lower.partial1.tvf_resonance"
    new_value = 30 if before[target]["value"] != 30 else 0
    edited = d50.setPatchParameters(original, {target: new_value})

    assert len(edited) == len(original)
    assert d50.d_50.isSingleProgramDump(edited) == d50.d_50.isSingleProgramDump(original)
    assert d50.d_50.isEditBufferDump(edited) == d50.d_50.isEditBufferDump(original)
    assert d50.nameFromDump(edited) == d50.nameFromDump(original)
    after = by_id(d50.getPatchParameters(edited))
    assert after[target]["value"] == new_value
    for parameter_id, p in before.items():
        if parameter_id != target:
            assert after[parameter_id]["value"] == p["value"], parameter_id

    # Only the data byte and that block's checksum differ, and every checksum is valid
    differences = [i for i in range(len(original)) if original[i] != edited[i]]
    assert 1 <= len(differences) <= 2
    for start, end in knobkraft.sysex.findSysexDelimiters(edited, 7):
        message = edited[start:end]
        assert message[-2] == d50.d_50.roland_checksum(message[d50.d_50._checksum_start():-2])


def test_bad_values_are_refused(patches):
    with pytest.raises(ValueError):
        d50.setPatchParameters(patches[0], {"patch.key_mode": 9})
    with pytest.raises(ValueError):
        d50.setPatchParameters(patches[0], {"patch.no_such_thing": 1})
    with pytest.raises(ValueError):
        d50.setPatchParameters([0xf0, 0x41, 0x00, 0x14, 0xf7], {"patch.key_mode": 1})


def test_other_data_has_no_parameters():
    assert d50.getPatchParameters([0xf0, 0x41, 0x00, 0x14, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0x40, 0xf7]) == []
