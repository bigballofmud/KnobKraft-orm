#
#   Copyright (c) 2021 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#

#
#   Built upon the Korg MS2000 file.
#
#   This works for program mode only, combination mode seems to be more complex to support
from typing import List

import knobkraft
import testing


def name():
    return "Korg 03R/W"


def createDeviceDetectMessage(channel):
    # This is a sysex generic device detect message
    return [0xf0, 0x7e, channel & 0x0f, 0x06, 0x01, 0xf7]


def deviceDetectWaitMilliseconds():
    return 200


def generalMessageDelay():
    # The 03R/W doesn't seem to like to get the messages too fast, so wait a bit between messages
    # The better implementation would be probably to do a handshake implementation, as it will likely reply
    # with a 0x23 DATA LOAD COMPLETED message on a program change message?
    return 400


def needsChannelSpecificDetection():
    return True


def channelIfValidDeviceResponse(message):
    # The MS2000 answers with 15 bytes
    # +---------+------------------------------------------------+
    # | Byte[H] |                Description                     |
    # +---------+------------------------------------------------+
    # |   F0    | Exclusive Status                               |
    # |   7E    | Non Realtime Message                           |
    # |   0g    | MIDI Global Channel  ( Device ID )             |
    # |   06    | General Information                            |
    # |   02    | Identity Reply                                 |
    # |   42    | KORG ID              ( Manufacturers ID )      |
    # |   30    | 03R/W                ( Family ID   (LSB))      |
    # |   00    |                      ( Family ID   (MSB))      |
    # |   00    |                      ( Member ID   (LSB))      |
    # |   00    |                      ( Member ID   (MSB))      |
    # |   xx    |                      ( Minor Ver.  (LSB))      |
    # |   xx    |                      ( Minor Ver.  (MSB))      |
    # |   xx    |                      ( Major Ver.  (LSB))      |
    # |   xx    |                      ( Major Ver.  (MSB))      |
    # |   F7    | END OF EXCLUSIVE                               |
    # +---------+------------------------------------------------+
    if (len(message) > 9
            and message[0] == 0xf0  # Sysex
            and message[1] == 0x7e  # Non-realtime
            and message[3] == 0x06  # Device request
            and message[4] == 0x02  # Device request reply
            and message[5] == 0x42  # KORG ID
            and message[6] == 0x30  # 03R/W
            and message[7] == 0x00
            and message[8] == 0x00  # 03R/W
            and message[9] == 0x00):
        # Extract the current MIDI channel from index 2 of the message
        return message[2]
    return -1


def createEditBufferRequest(channel):
    # (2) CURRENT PROGRAM DATA DUMP REQUEST                              R
    # +----------------+--------------------------------------------------+
    # |     Byte       |             Description                          |
    # +----------------+--------------------------------------------------+
    # | F0,42,3g,30    | EXCLUSIVE HEADER                                 |
    # | 0001 0000 (10) | CURRENT PROGRAM DATA DUMP REQUEST      10H       |
    # | 1111 0111 (F7) | EOX                                              |
    # +----------------+--------------------------------------------------+
    return [0xf0, 0x42, 0x30 | (channel & 0x0f), 0x30, 0x10, 0xf7]


def isEditBufferDump(message):
    # +----------------+--------------------------------------------------+
    # |     Byte       |             Description                          |
    # +----------------+--------------------------------------------------+
    # | F0,42,3g,58    | EXCLUSIVE HEADER                                 |
    # | 0100 0000 (40) | CURRENT PROGRAM DATA DUMP              40H       |
    # | 0000 0000 (00) |                                                  |
    # | 0ddd dddd (dd) | Data                                  (NOTE 1,6) |
    # |     :          |  :                                               |
    # | 1111 0111 (F7) | EOX                                              |
    # +----------------+--------------------------------------------------+
    return (len(message) > 4
            and message[0] == 0xf0
            and message[1] == 0x42  # Korg
            and (message[2] & 0xf0) == 0x30
            and message[3] == 0x30  # 03R:W
            and message[4] == 0x40)  # Current Program Data Dump


def numberOfBanks():
    return 1


def numberOfPatchesPerBank():
    return 100


def nameFromDump(message):
    if isEditBufferDump(message):
        # We need to first convert from 7 bit data to 8 bit data, before we can extract the program name
        patchData = unescapeSysex(message[5:-1])
        return ''.join([chr(x) for x in patchData[0:10]])
    return "Invalid"


def convertToEditBuffer(channel, message):
    if isEditBufferDump(message):
        # The data structures are the same, only byte 2 seems to contain the device ID (or channel), and
        # byte 4 should be 0x40, current program data dump
        return message[0:2] + [0x030 | (channel & 0x0f), 0x30, 0x40] + message[5:]
    raise Exception("Neither edit buffer nor program dump can't be converted")


def createBankDumpRequest(channel, bank):
    # |     1C      | PROGRAM DATA DUMP REQUEST                  |
    return [0xf0, 0x42, 0x30 | (channel & 0x0f), 0x30, 0x1c, 0x00, 0xf7]


def isPartOfBankDump(message):
    return (len(message) > 4
            and message[0] == 0xf0
            and message[1] == 0x42  # Korg
            and (message[2] & 0xf0) == 0x30
            and message[3] == 0x30  # 03R/W
            and (message[4] == 0x40 or message[4] == 0x4c))  # Program Data dump or All Data dump


def isBankDumpFinished(messages):
    for message in messages:
        if isPartOfBankDump(message):
            return True
    return False


def extractPatchesFromBank(message):
    if isPartOfBankDump(message):
        channel = message[2] & 0x0f
        data = unescapeSysex(message[6:-1])
        # There are different files out there with different number of patches (64 or 128), plus the global data
        data_pointer = 0
        result = []
        while data_pointer + 171 < len(data):
            # Read one more patch
            next_patch = data[data_pointer:data_pointer + 172]
            next_program_dump = [0xf0, 0x42, 0x30 | (channel & 0x0f), 0x30, 0x40] + escapeSysex(next_patch) + [0xf7]
            #print("Found patch " + nameFromDump(next_program_dump))
            result = result + next_program_dump
            data_pointer = data_pointer + 172
        return result
    raise Exception("This code can only read a single message of type 'ALL DATA DUMP'")


def unescapeSysex(sysex):
    result = []
    dataIndex = 0
    while dataIndex < len(sysex):
        # The first byte contains the highest (most significant = MS) bit of the next seven data bytes
        ms_bits = sysex[dataIndex]
        dataIndex += 1
        for i in range(7):
            if dataIndex < len(sysex):
                result.append(sysex[dataIndex] | ((ms_bits & (1 << i)) << (7 - i)))
            dataIndex += 1
    return result


def escapeSysex(data):
    result = []
    dataIndex = 0
    while dataIndex < len(data):
        ms_bits = 0
        for i in range(7):
            if dataIndex + i < len(data):
                ms_bits = ms_bits | ((data[dataIndex + i] & 0x80) >> (7 - i))
        result.append(ms_bits)
        for i in range(7):
            if dataIndex + i < len(data):
                result.append(data[dataIndex + i] & 0x7f)
        dataIndex += 7
    return result


def make_test_data():
    testData = [x for x in range(254)]
    escaped = escapeSysex(testData)
    back = unescapeSysex(escaped)
    assert testData == back

    def programs(data: testing.TestData) -> List[testing.ProgramTestData]:
        patches = knobkraft.splitSysex(extractPatchesFromBank(data.all_messages[0]))
        yield testing.ProgramTestData(message=patches[0], name='AnalogFeel')

    def banks(data: testing.TestData) -> List:
        yield data.all_messages

    return testing.TestData(sysex="testData/Korg_03RW/vicbank1.syx", edit_buffer_generator=programs, bank_generator=banks, expected_patch_count=100)


# ---------------------------------------------------------------------------------------------------------------------
# Parameter grid: getPatchParameters / setPatchParameters
#
# Korg publishes no MIDI implementation for the 03R/W itself. Its programs use the layout of the 01/W family: the
# PROGRAM PARAMETER table (TABLE 1) in the MIDI implementation of Korg's 01/W FD / 01/W owner's manual, 172 bytes.
# Checked against a real 03R/W bank: every value of all 100 programs lies in that table's ranges. The 03R/W has no
# wave shaping (those bytes hold "off" in every program), so bytes 82-86 and 133-137 are not shown, and neither are
# the effect parameters (143-171).
# ---------------------------------------------------------------------------------------------------------------------

_PROGRAM_SIZE = 172
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _number(value):
    return str(value)


def _signed_text(value):
    return f"+{value}" if value > 0 else str(value)


def _choice_text(*names):
    def text(value):
        return names[value] if 0 <= value < len(names) else str(value)
    text.options = list(names)
    return text


def _key_name(value):
    return f"{_NOTE_NAMES[value % 12]}{value // 12 - 1}"  # 00 = C-1, 7F = G9


# The 03R/W's internal multisounds 000-254, from the Multi Sound Name list in its owner's manual
_MULTISOUND_NAMES = [
    'A.Piano', 'E.Piano 1', 'E.Piano1LP', 'E.Piano 2', 'E.Piano2LP', 'Hard EP', 'Hard EP LP', 'Soft EP',
    'Soft EP LP', 'PianoPad 1', 'P.Pad 1 LP', 'PianoPad 2', 'P.Pad 2 LP', 'Clav', 'Clav LP', 'Harpsicord',
    'HarpsicdLP', 'PercOrgan1', 'PercOrg1LP', 'PercOrgan2', 'PercOrg2LP', 'Organ 1', 'Organ 1 LP', 'Organ 2',
    'Organ 2 LP', 'PipeOrgan1', 'PipeOrg1LP', 'PipeOrgan2', 'Accordion', 'AcordionLP', 'G.Guitar', 'G.GuitarLP',
    'F.Guitar', 'F.GuitarLP', 'A.Gtr Harm', 'Hard Pick', 'E.Guitar', 'MuteGuitar', 'Gtr Harm 1', 'Gtr Harm 2',
    'DistGuitar', 'Dist GtrLP', 'Sitar', 'Banjo', 'Shamisen', 'Koto', 'Harp', 'A.Bass 1',
    'A.Bass 2', 'A.Bass2 LP', 'A.Bass 3', 'A.Bass3 LP', 'Fretless', 'FretlessLP', 'E.Bass 1', 'E.Bass 2',
    'E.Bass 3', 'E.Bass3 LP', 'Slap Bass1', 'SlpBass1LP', 'Slap Bass2', 'SynthBass1', 'SynthBass2', 'Tech Bass',
    'TechBassLP', 'Kalimba', 'Music Box', 'Log Drum', 'Marimba', 'Vibe', 'BrightBell', 'B.Bell LP',
    'Metal Bell', 'M.Bell LP', 'Gamelan', 'Pole', 'Pole LP', 'Tubular', 'Gong 1', 'Gong 1 LP',
    'Gong 2', 'Gong 2 LP', 'Split Bell', 'Tuned bell', 'Harmonica', 'HardFlute1', 'HardFlute2', 'Pan Flute',
    'PanFluteLP', 'Shakuhachi', 'Bottle', 'Bassoon', 'Oboe', 'EnglishHrn', 'Eng.HornLP', 'BassonOboe',
    'BsonOboeLP', 'Clarinet', 'ClarinetLP', 'Bari.Sax', 'Bari.SaxLP', 'Tenor Sax', 'T.Sax LP', 'Alto Sax',
    'A.Sax LP', 'SopranoSax', 'S.Sax LP', 'Tuba/FrH', 'Tuba/FrHLP', 'Trombone 1', 'Trombone 2', 'Mute Tromb',
    'Trumpet', 'Trumpet LP', 'Mute TP', 'Mute TP LP', 'Brass 1', 'Brass 2', 'StringEns.', 'StrEns.LP1',
    'StrEns.LP2', 'StrEns.LP3', 'AnaStrings', 'PWM', 'Violin', 'Cello', 'Pizzicato', 'Voice',
    'Choir', 'Soft Choir', 'Air Vox', 'Chorello', 'Doo Vox', 'Syn Vox', 'Syn Vox LP', 'Lub Wave',
    'Ether Bell', 'Ghostly', 'Spectrum', 'Stadium', 'Stadium NT', 'Belltree', 'BelltreeNT', 'Tri Roll',
    'TriRoll NT', 'Clicker', 'Clicker NT', 'Lore', 'Lore NT', 'Crickets', 'Crickts NT', 'MagicBell',
    'Tron Up', 'TronUp LP', 'TronUp NT', 'Flutter', 'Flutter LP', 'Tap 1', 'Tap 2', 'Tap 3',
    'Tap 4', 'Tap 5', 'Tap 6', 'Orch Hit', 'Snare Cast', 'Syn Snare', 'Rev Snare', 'Fist',
    'CrshCymbal', 'Orch Perc', 'Hi Hat', 'Hi Hat NT', 'Bell Ride', 'Ping Ride', 'ProccesTom', 'Timpani',
    'Timpani LP', 'Cabasa', 'Cabasa NT', 'Agogo', 'Cowbell', 'Low Bongo', 'Claves', 'Timbales',
    'WoodBlock1', 'WoodBlock2', 'Vibe Hit', 'Syn Claves', 'A.Tom', 'Syn Tom', 'Zap 1', 'Zap 2',
    'Industry 1', 'Industr1NT', 'Industry 2', 'Industr2NT', 'Rev Thing', 'FingerSnap', 'FngrSnapNT', 'Pop',
    'Tambourine', 'Hand Claps', 'HandClpsNT', 'Castanet', 'CastanetNT', 'Snap', 'Slurp', 'Slurp NT',
    'Gt Scratch', 'Side Stick', 'SideStckNT', 'Syn Rim', 'Syn Rim NT', 'L-Shaker', 'Open HH', 'CloseSynHH',
    'Open SynHH', 'Taiko', 'Lo Bongo', 'Slap Bongo', 'Stick Hit', 'StickHitNT', 'Open Conga', 'Slap Conga',
    'Palm Conga', 'Mute Conga', 'Maracas', 'MuteTriang', 'OpenTriang', 'Scratch Hi', 'Scratch Lo', 'ScratchDbl',
    'Mini 1a', 'VS 102', 'VS 58', 'VS 71', 'VS 72', 'VS 88', 'VS 89', '13-35',
    'DWGS Clav', 'DWGSOrgan1', 'DWGSOrgan2', 'DWGS E.P.1', 'DWGS E.P.2', 'Saw', 'Ramp', 'Square',
    'Pulse 25%', 'Pulse 16%', 'Pulse 8%', 'Pulse 4%', 'Syn Sine 1', 'Syn Sine 2', 'Sine',
]


def _multisound(value):
    # TABLE 1 writes "0, 1~FF : OFF, 0~254", but real 03R/W programs store the multisound number itself
    # ("Saw Solo" uses 245 = Saw, "Square?" 247 = Square, "Trumpet X" 112 = Trumpet), so FF is OFF
    if value == 0xff:
        return "OFF"
    return f"{value:03d} {_MULTISOUND_NAMES[value]}" if value < len(_MULTISOUND_NAMES) else str(value)


def _bank(value):
    return "Int" if value < 0x10 else "Ext"


def _pan(value):
    if value <= 10:
        return f"A{10 - value}:B{value}"
    return {11: "C", 12: "C+D", 13: "D", 14: "ALL"}.get(value, str(value))


_OFF_ON = _choice_text("OFF", "ON")
_MG_WAVE = _choice_text("Triangle", "Up saw", "Down saw", "Rectangle", "Random")
_KBD_TRACK_MODE = _choice_text("OFF", "LOW", "HIGH", "ALL")
_POLARITY = _choice_text("+", "-")


def _field(byte, name, low, high, text=_number, shift=0, width=8, editable=True):
    """One parameter: a bit field of a byte; low < 0 means the byte holds a signed (two's complement) value."""
    return {"byte": byte, "name": name, "min": low, "max": high, "text": text, "shift": shift, "width": width,
            "signed": low < 0, "editable": editable}


def _u99(byte, name):
    return _field(byte, name, 0, 99)


def _s99(byte, name):
    return _field(byte, name, -99, 99, _signed_text)


_COMMON_SECTIONS = [
    ("Oscillators", "osc", [
        _field(10, "Oscillator mode", 0, 2, _choice_text("Single", "Double", "Drums")),
        _field(11, "Assign", 0, 1, _choice_text("Poly", "Mono"), shift=0, width=1),
        _field(11, "Hold", 0, 1, _OFF_ON, shift=1, width=1),
        _field(12, "OSC-1 multisound", 0, 255, _multisound),
        _field(13, "OSC-1 multisound bank", 0, 0x1f, _bank, editable=False),
        _field(14, "OSC-1 octave", -2, 1, lambda v: {-2: "32'", -1: "16'", 0: "8'", 1: "4'"}.get(v, str(v))),
        _field(15, "OSC-2 multisound", 0, 255, _multisound),
        _field(16, "OSC-2 multisound bank", 0, 0x1f, _bank, editable=False),
        _field(17, "OSC-2 octave", -2, 1, lambda v: {-2: "32'", -1: "16'", 0: "8'", 1: "4'"}.get(v, str(v))),
        _field(18, "Interval", -12, 12, _signed_text),
        _field(19, "Detune", -50, 50, _signed_text),
        _u99(20, "Delay start"),
    ]),
    ("Pitch EG", "pitch_eg", [
        _s99(21, "Start level"), _u99(22, "Attack time"), _s99(23, "Attack level"), _u99(24, "Decay time"),
        _u99(25, "Release time"), _s99(26, "Release level"), _s99(27, "Time velocity sense"), _s99(28, "Level velocity sense"),
    ]),
    ("Cutoff MG", "cutoff_mg", [
        _field(29, "Waveform", 0, 4, _MG_WAVE, shift=0, width=3),
        _field(29, "OSC-1 MG enable", 0, 1, _OFF_ON, shift=5, width=1),
        _field(29, "OSC-2 MG enable", 0, 1, _OFF_ON, shift=6, width=1),
        _field(29, "Key sync", 0, 1, _OFF_ON, shift=7, width=1),
        _u99(30, "Frequency"), _u99(31, "Delay"), _u99(32, "Intensity"),
    ]),
    ("Aftertouch & joystick", "control", [
        _field(33, "Aftertouch pitch bend range", -12, 12, _signed_text),
        _s99(34, "Aftertouch VDF cutoff"), _u99(35, "Aftertouch VDF MG int"), _s99(36, "Aftertouch VDA amplitude"),
        _field(37, "Joystick pitch bend range", -12, 12, _signed_text),
        _s99(38, "Joystick VDF sweep int"), _u99(39, "Joystick VDF MG int"),
    ]),
]


def _oscillator_sections(osc: int, base: int):
    b = base
    pitch = [
        _s99(b + 0, "Pitch EG int"),
        _field(b + 1, "Pitch MG waveform", 0, 4, _MG_WAVE, shift=0, width=3),
        _field(b + 1, "Pitch MG key sync", 0, 1, _OFF_ON, shift=7, width=1),
        _u99(b + 2, "Pitch MG frequency"), _u99(b + 3, "Pitch MG delay"), _u99(b + 4, "Pitch MG fade in"),
        _u99(b + 5, "Pitch MG intensity"), _s99(b + 6, "Pitch MG freq mod by kbd track"),
        _u99(b + 7, "Pitch MG intensity mod by AT"), _u99(b + 8, "Pitch MG intensity mod by JS"),
        _field(b + 9, "Pitch MG freq mod by AT+JS", 0, 9),
    ]
    vdf = [
        _u99(b + 10, "VDF cutoff value"), _field(b + 11, "VDF kbd track key", 0, 127, _key_name),
        _s99(b + 12, "VDF cutoff kbd track"), _u99(b + 13, "VDF EG intensity"), _u99(b + 14, "VDF EG time kbd track"),
        _u99(b + 15, "VDF EG time vel sense"), _s99(b + 16, "VDF EG int vel sense"),
        _u99(b + 17, "VDF EG attack time"), _s99(b + 18, "VDF EG attack level"), _u99(b + 19, "VDF EG decay time"),
        _s99(b + 20, "VDF EG break point"), _u99(b + 21, "VDF EG slope time"), _s99(b + 22, "VDF EG sustain level"),
        _u99(b + 23, "VDF EG release time"), _s99(b + 24, "VDF EG release level"),
        _u99(b + 47, "Emphasis intensity"), _s99(b + 48, "Emphasis velocity sense"),
        _field(b + 49, "VDF kbd track mode", 0, 3, _KBD_TRACK_MODE, shift=0, width=2),
    ]
    vda = [
        _u99(b + 25, "VDA oscillator level"), _field(b + 26, "VDA kbd track key", 0, 127, _key_name),
        _s99(b + 27, "VDA amp kbd track int"), _s99(b + 28, "VDA amp velocity sense"),
        _u99(b + 29, "VDA EG time kbd track"), _u99(b + 30, "VDA EG time vel sense"),
        _u99(b + 31, "VDA EG attack time"), _u99(b + 32, "VDA EG attack level"), _u99(b + 33, "VDA EG decay time"),
        _u99(b + 34, "VDA EG break point"), _u99(b + 35, "VDA EG slope time"), _u99(b + 36, "VDA EG sustain level"),
        _u99(b + 37, "VDA EG release time"),
        _field(b + 49, "VDA kbd track mode", 0, 3, _KBD_TRACK_MODE, shift=4, width=2),
        _field(b + 50, "Pan", 0, 14, _pan),
    ]
    switches = []
    for byte, prefix in ((b + 38, "VDF EG time kbd track"), (b + 39, "VDF EG time vel"),
                         (b + 40, "VDA EG time kbd track"), (b + 41, "VDA EG time vel")):
        for bit, stage in enumerate(("attack", "decay", "slope", "release")):
            switches.append(_field(byte, f"{prefix} {stage}", 0, 1, _OFF_ON, shift=bit, width=1))
        for bit, stage in enumerate(("attack", "decay", "slope", "release")):
            switches.append(_field(byte, f"{prefix} {stage} polarity", 0, 1, _POLARITY, shift=4 + bit, width=1))
    prefix = f"osc{osc}"
    return [(f"OSC-{osc} pitch", f"{prefix}.pitch", pitch), (f"OSC-{osc} VDF", f"{prefix}.vdf", vdf),
            (f"OSC-{osc} VDA", f"{prefix}.vda", vda), (f"OSC-{osc} EG time switches", f"{prefix}.eg_switch", switches)]


def _program_layout():
    result = []
    for group, prefix, fields in _COMMON_SECTIONS + _oscillator_sections(1, 40) + _oscillator_sections(2, 91):
        for field in fields:
            entry = dict(field)
            entry["group"] = group
            entry["id"] = prefix + "." + field["name"].lower().replace(" ", "_").replace("-", "").replace("+", "_").replace("&", "and")
            result.append(entry)
    return result


_PROGRAM_LAYOUT = _program_layout()


def _program_data(message):
    if not isEditBufferDump(message) or message[-1] != 0xf7:
        return None
    data = unescapeSysex(message[5:-1])
    return data if len(data) >= _PROGRAM_SIZE else None


def _read(data, field):
    raw = (data[field["byte"]] >> field["shift"]) & ((1 << field["width"]) - 1)
    if field["signed"] and raw > 127:
        raw -= 256
    return raw


def getPatchParameters(message):
    data = _program_data(message)
    if data is None:
        return []
    result = []
    drums = data[10] == 2
    for field in _PROGRAM_LAYOUT:
        value = _read(data, field)
        text = field["text"](value)
        if field["id"] == "osc.osc1_multisound" and drums:
            text = f"Drum kit {value + 1}"  # In Drums mode this byte picks the drum kit
        parameter = {"id": field["id"], "name": field["name"], "group": field["group"], "value": value,
                     "min": field["min"], "max": field["max"], "text": text, "editable": field["editable"]}
        if hasattr(field["text"], "options"):
            parameter["options"] = field["text"].options
        result.append(parameter)
    return result


def setPatchParameters(message, values):
    """The program with the given values written in, in the same message format and channel as the input."""
    data = _program_data(message)
    if data is None:
        raise ValueError("Not a 03R/W program dump")
    by_id = {field["id"]: field for field in _PROGRAM_LAYOUT}
    for parameter_id, value in values.items():
        field = by_id.get(parameter_id)
        if field is None or not field["editable"]:
            raise ValueError(f"Unknown or read-only 03R/W parameter '{parameter_id}'")
        if not field["min"] <= value <= field["max"]:
            raise ValueError(f"Value {value} out of range {field['min']}..{field['max']} for '{parameter_id}'")
        mask = ((1 << field["width"]) - 1) << field["shift"]
        raw = (value & 0xff) if field["signed"] else value
        data[field["byte"]] = (data[field["byte"]] & ~mask & 0xff) | ((raw << field["shift"]) & mask)
    return message[0:5] + escapeSysex(data) + [0xf7]
