#
#   Copyright (c) 2026 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#
#   Tests for the Korg 03R/W parameter grid (getPatchParameters / setPatchParameters).
#
#   Korg publishes no MIDI implementation for the 03R/W; the layout is the 01/W family's PROGRAM PARAMETER
#   table (TABLE 1 in Korg's 01/W FD / 01/W owner's manual). The real bank in testData/Korg_03RW checks it:
#   all 100 programs must decode inside the table's ranges, and program names must match their multisounds.
#

import pytest

import knobkraft
import Korg_03RW as k03


@pytest.fixture(scope="module")
def programs():
    messages = knobkraft.load_sysex("testData/Korg_03RW/vicbank1.syx", as_single_list=False)
    result = knobkraft.splitSysex(k03.extractPatchesFromBank(messages[0]))
    assert len(result) == 100
    return result


def by_id(parameters):
    return {p["id"]: p for p in parameters}


def program_named(programs, name):
    return next(p for p in programs if k03.nameFromDump(p).strip() == name)


def test_every_value_of_a_real_bank_is_in_range(programs):
    for program in programs:
        parameters = k03.getPatchParameters(program)
        assert len(parameters) == 186
        for p in parameters:
            assert p["min"] <= p["value"] <= p["max"], (k03.nameFromDump(program), p["id"], p["value"])


def test_ids_are_unique_and_sections_in_order(programs):
    parameters = k03.getPatchParameters(programs[0])
    assert len({p["id"] for p in parameters}) == len(parameters)
    groups = []
    for p in parameters:
        if p["group"] not in groups:
            groups.append(p["group"])
    assert groups == ["Oscillators", "Pitch EG", "Cutoff MG", "Aftertouch & joystick",
                      "OSC-1 pitch", "OSC-1 VDF", "OSC-1 VDA", "OSC-1 EG time switches",
                      "OSC-2 pitch", "OSC-2 VDF", "OSC-2 VDA", "OSC-2 EG time switches"]


def test_multisounds_match_the_program_names(programs):
    # The byte is the multisound number itself, not number + 1 as TABLE 1 could be read
    assert by_id(k03.getPatchParameters(program_named(programs, "Saw Solo")))["osc.osc1_multisound"]["text"] == "245 Saw"
    assert by_id(k03.getPatchParameters(program_named(programs, "Square?")))["osc.osc1_multisound"]["text"] == "247 Square"
    assert by_id(k03.getPatchParameters(program_named(programs, "Trumpet X")))["osc.osc1_multisound"]["text"] == "112 Trumpet"
    assert by_id(k03.getPatchParameters(program_named(programs, "PWM 00")))["osc.osc1_multisound"]["text"] == "123 PWM"
    assert k03._multisound(0xff) == "OFF"
    assert len(k03._MULTISOUND_NAMES) == 255


def test_drum_programs_show_their_drum_kit(programs):
    values = by_id(k03.getPatchParameters(program_named(programs, "Crazy Drum")))
    assert values["osc.oscillator_mode"]["text"] == "Drums"
    assert values["osc.osc1_multisound"]["text"] == "Drum kit 1"


def test_signed_values_and_texts(programs):
    values = by_id(k03.getPatchParameters(program_named(programs, "AnalogFeel")))
    assert values["osc.oscillator_mode"]["text"] == "Double"
    assert values["osc.osc1_octave"]["value"] == -1 and values["osc.osc1_octave"]["text"] == "16'"
    assert values["osc.detune"]["value"] == -4
    assert k03._key_name(0) == "C-1" and k03._key_name(60) == "C4" and k03._key_name(127) == "G9"
    assert k03._pan(0) == "A10:B0" and k03._pan(10) == "A0:B10" and k03._pan(14) == "ALL"
    assert values["osc.osc1_multisound_bank"]["editable"] is False


def test_unchanged_write_returns_the_same_message(programs):
    for program in programs:
        assert k03.setPatchParameters(program, {}) == program


@pytest.mark.parametrize("parameter_id, new_value", [
    ("osc.detune", -50),                                  # signed byte
    ("pitch_eg.attack_level", 99),
    ("cutoff_mg.osc2_mg_enable", 1),                      # single bit in a shared byte
    ("cutoff_mg.waveform", 4),                            # 3-bit field in the same byte
    ("osc2.vda.vda_kbd_track_mode", 2),                   # upper nibble pair, shares its byte with VDF mode
    ("osc1.eg_switch.vda_eg_time_vel_release_polarity", 1),
    ("osc2.vdf.vdf_eg_release_level", -99),
])
def test_setting_a_value_changes_only_that_parameter(programs, parameter_id, new_value):
    original = program_named(programs, "AnalogFeel")
    before = by_id(k03.getPatchParameters(original))
    if before[parameter_id]["value"] == new_value:
        new_value = before[parameter_id]["min"]
    edited = k03.setPatchParameters(original, {parameter_id: new_value})
    assert k03.isEditBufferDump(edited) and len(edited) == len(original)
    assert edited[:5] == original[:5]
    assert k03.nameFromDump(edited) == k03.nameFromDump(original)
    after = by_id(k03.getPatchParameters(edited))
    assert after[parameter_id]["value"] == new_value
    for other, p in before.items():
        if other != parameter_id:
            assert after[other]["value"] == p["value"], other
    # The bytes the grid doesn't show (wave shaping, effects) stay as they were
    old_data, new_data = k03.unescapeSysex(original[5:-1]), k03.unescapeSysex(edited[5:-1])
    for byte in list(range(82, 87)) + list(range(133, 138)) + list(range(142, 172)):
        assert old_data[byte] == new_data[byte], byte


def test_bad_values_are_refused(programs):
    with pytest.raises(ValueError):
        k03.setPatchParameters(programs[0], {"osc.detune": 51})
    with pytest.raises(ValueError):
        k03.setPatchParameters(programs[0], {"osc.osc1_multisound_bank": 1})  # Read-only
    with pytest.raises(ValueError):
        k03.setPatchParameters(programs[0], {"osc.no_such_thing": 1})
    assert k03.getPatchParameters([0xf0, 0x42, 0x30, 0x30, 0x10, 0xf7]) == []
