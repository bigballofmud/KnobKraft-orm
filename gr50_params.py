# Roland GR-50 SysEx Parameter Map
# Derived from Owner's Manual (OCR). OCR ambiguities marked with # OCR NOTE.
#
# PROTOCOL SUMMARY
# ----------------
# Manufacturer ID : 0x41 (Roland)
# Model ID        : 0x16
# Device ID       : Unit# - 1  (range 0x10–0x1F; set in System Setup)
# Address space   : 3 bytes, each 7-bit (0x00–0x7F)
# Checksum        : (-sum(addr + size_or_data)) & 0x7F
# Max payload     : 256 bytes per DT1/DAT message; split larger transfers
#
# ONE-WAY (small transfers)
#   RQ1 (request) : F0 41 dev 16 11 aa aa aa ss ss ss sum F7
#   DT1 (data)    : F0 41 dev 16 12 aa aa aa dd ... sum F7
#
# HANDSHAKE (bulk transfers)
#   WSD : F0 41 dev 16 40 aa aa aa ss ss ss sum F7  (want to send)
#   RQD : F0 41 dev 16 41 aa aa aa ss ss ss sum F7  (request data)
#   DAT : F0 41 dev 16 42 aa aa aa dd ... sum F7    (data block)
#   ACK : F0 41 dev 16 43 F7
#   EOD : F0 41 dev 16 45 F7
#   ERR : F0 41 dev 16 4E F7
#   RJC : F0 41 dev 16 4F F7
#
# ADDRESSING
#   Real address = parameter_base_address + offset
#   The 'address' key in each base entry is [MSB, MID, LSB].
#   Offsets in offset tables are simple integers added to LSB
#   (with carry into MID/MSB as needed for 7-bit arithmetic).
#
# PARAMETER ENCODING
#   The 'bits' string (e.g. '0000aaaa') shows which bits are active.
#   'range' is [min, max] of the raw 7-bit value sent over MIDI.
#   'display' describes the human-readable mapping where non-obvious.


# ---------------------------------------------------------------------------
# Offset tables (shared by temporary and memory areas of the same type)
# ---------------------------------------------------------------------------

TIMBRE_TEMPORARY_PARAMS = {
    # Table 1 — 16 bytes total
    '_total_size': 0x10,
    'params': [
        {'offset': 0x00, 'bits': '000000aa', 'name': 'tone_group',    'range': (0, 3),   'labels': ('a', 'b', 'i/c', 'l')},
        {'offset': 0x01, 'bits': '00aaaaaa', 'name': 'tone_number',   'range': (0, 63),  'display': '1–64'},
        {'offset': 0x02, 'bits': '00aaaaaa', 'name': 'key_shift',     'range': (0, 48),  'display': '-24 to +24'},
        {'offset': 0x03, 'bits': '0aaaaaaa', 'name': 'fine_tune',     'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x04, 'bits': '000aaaaa', 'name': 'bender_range',  'range': (0, 24)},
        {'offset': 0x05, 'bits': '000000aa', 'name': 'assign_mode',   'range': (0, 3),   'labels': ('poly1', 'poly2', 'poly3', 'poly4')},
        {'offset': 0x06, 'bits': '0000000a', 'name': 'reverb_switch', 'range': (0, 1),   'labels': ('off', 'on')},
        {'offset': 0x07, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x08, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x09, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x0A, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x0B, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x0C, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x0D, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x0E, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x0F, 'bits': '0xxxxxxx', 'name': '_reserved'},
    ],
}

TIMBRE_MEMORY_PARAMS = {
    # Table 1a — 8 bytes (half of temporary; no reserved tail)
    '_total_size': 0x08,
    'params': [
        {'offset': 0x00, 'bits': '000000aa', 'name': 'tone_group',    'range': (0, 3),   'labels': ('a', 'b', 'i/c', 'l')},
        {'offset': 0x01, 'bits': '00aaaaaa', 'name': 'tone_number',   'range': (0, 63),  'display': '1–64'},
        {'offset': 0x02, 'bits': '00aaaaaa', 'name': 'key_shift',     'range': (0, 48),  'display': '-24 to +24'},
        {'offset': 0x03, 'bits': '0aaaaaaa', 'name': 'fine_tune',     'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x04, 'bits': '000aaaaa', 'name': 'bender_range',  'range': (0, 24)},
        {'offset': 0x05, 'bits': '000000aa', 'name': 'assign_mode',   'range': (0, 3),   'labels': ('poly1', 'poly2', 'poly3', 'poly4')},
        {'offset': 0x06, 'bits': '0000000a', 'name': 'reverb_switch', 'range': (0, 1),   'labels': ('off', 'on')},
        {'offset': 0x07, 'bits': '0xxxxxxx', 'name': '_reserved'},
    ],
}

RHYTHM_SETUP_PARAMS = {
    # Table 2 — 4 bytes
    '_total_size': 0x04,
    'params': [
        {'offset': 0x00, 'bits': '00aaaaaa', 'name': 'tone',         'range': (0, 63),  'display': 'r01–r64'},
        {'offset': 0x01, 'bits': '0aaaaaaa', 'name': 'output_level', 'range': (0, 100)},
        {'offset': 0x02, 'bits': '00aaaaaa', 'name': 'panpot',       'range': (0, 14),  'display': 'left–right'},
        {'offset': 0x03, 'bits': '0aaaaaaa', 'name': 'reverb_switch','range': (0, 1),   'labels': ('off', 'on')},
    ],
}

TONE_COMMON_PARAMS = {
    # Table 3-1 — 14 bytes
    '_total_size': 0x0E,
    'params': [
        {'offset': 0x00, 'bits': '0aaaaaaa', 'name': 'tone_name_1',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x01, 'bits': '0aaaaaaa', 'name': 'tone_name_2',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x02, 'bits': '0aaaaaaa', 'name': 'tone_name_3',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x03, 'bits': '0aaaaaaa', 'name': 'tone_name_4',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x04, 'bits': '0aaaaaaa', 'name': 'tone_name_5',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x05, 'bits': '0aaaaaaa', 'name': 'tone_name_6',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x06, 'bits': '0aaaaaaa', 'name': 'tone_name_7',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x07, 'bits': '0aaaaaaa', 'name': 'tone_name_8',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x08, 'bits': '0aaaaaaa', 'name': 'tone_name_9',   'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x09, 'bits': '0aaaaaaa', 'name': 'tone_name_10',  'range': (32, 127), 'display': 'ASCII'},
        {'offset': 0x0A, 'bits': '0000aaaa', 'name': 'structure_1_2', 'range': (0, 12),   'display': '1–13'},
        {'offset': 0x0B, 'bits': '0000aaaa', 'name': 'structure_3_4', 'range': (0, 12),   'display': '1–13'},
        {'offset': 0x0C, 'bits': '0000aaaa', 'name': 'partial_mute',  'range': (0, 15),   'display': 'bitmask: bit0=P1 ... bit3=P4'},
        {'offset': 0x0D, 'bits': '0000000a', 'name': 'envelope_mode', 'range': (0, 1),    'labels': ('normal', 'no_sustain')},
    ],
}

TONE_PARTIAL_PARAMS = {
    # Table 3-2 — 58 bytes; same layout for partials 1–4
    '_total_size': 0x3A,
    'params': [
        {'offset': 0x00, 'bits': '0aaaaaaa', 'name': 'wg_pitch_coarse',         'range': (0, 96),  'display': '-48 to +48 semitones'},  # OCR NOTE: '0-8-ce' → 0-96
        {'offset': 0x01, 'bits': '0aaaaaaa', 'name': 'wg_pitch_fine',           'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x02, 'bits': '000aaaaa', 'name': 'wg_pitch_key_follow',     'range': (0, 16)},
        {'offset': 0x03, 'bits': '0000000a', 'name': 'wg_pitch_bender_switch',  'range': (0, 1),   'labels': ('off', 'on')},
        {'offset': 0x04, 'bits': '000000aa', 'name': 'wg_pcm_bank_wave_form',   'range': (0, 3)},
        {'offset': 0x05, 'bits': '0aaaaaaa', 'name': 'wg_pcm_wave_number',      'range': (0, 127), 'display': '1–128'},
        {'offset': 0x06, 'bits': '0aaaaaaa', 'name': 'wg_pulse_width',          'range': (0, 100)},
        {'offset': 0x07, 'bits': '0000aaaa', 'name': 'wg_pulse_width_velo_sens','range': (0, 14),  'display': '-7 to +7'},
        {'offset': 0x08, 'bits': '0000aaaa', 'name': 'pitch_env_depth',         'range': (0, 10)},
        {'offset': 0x09, 'bits': '0aaaaaaa', 'name': 'pitch_env_velocity',      'range': (0, 100)},
        {'offset': 0x0A, 'bits': '00000aaa', 'name': 'pitch_env_time_key_follow','range': (0, 4)},
        {'offset': 0x0B, 'bits': '0aaaaaaa', 'name': 'pitch_env_time_1',        'range': (0, 100)},
        {'offset': 0x0C, 'bits': '0aaaaaaa', 'name': 'pitch_env_time_2',        'range': (0, 100)},
        {'offset': 0x0D, 'bits': '0aaaaaaa', 'name': 'pitch_env_time_3',        'range': (0, 100)},
        {'offset': 0x0E, 'bits': '0aaaaaaa', 'name': 'pitch_env_time_4',        'range': (0, 100)},
        {'offset': 0x0F, 'bits': '0aaaaaaa', 'name': 'pitch_env_level_0',       'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x10, 'bits': '0aaaaaaa', 'name': 'pitch_env_level_1',       'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x11, 'bits': '0aaaaaaa', 'name': 'pitch_env_level_2',       'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x12, 'bits': '0aaaaaaa', 'name': 'pitch_env_sus_level',     'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x13, 'bits': '0aaaaaaa', 'name': 'pitch_env_end_level',     'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x14, 'bits': '0aaaaaaa', 'name': 'pitch_lfo_rate',          'range': (0, 100)},
        {'offset': 0x15, 'bits': '0aaaaaaa', 'name': 'pitch_lfo_depth',         'range': (0, 100)},
        {'offset': 0x16, 'bits': '0aaaaaaa', 'name': 'pitch_lfo_mod_sens',      'range': (0, 100)},
        {'offset': 0x17, 'bits': '0aaaaaaa', 'name': 'tvf_cutoff',              'range': (0, 100)},
        {'offset': 0x18, 'bits': '000aaaaa', 'name': 'tvf_resonance',           'range': (0, 30)},
        {'offset': 0x19, 'bits': '0000aaaa', 'name': 'tvf_key_follow',          'range': (0, 14)},  # OCR NOTE: 'o-uci-'
        {'offset': 0x1A, 'bits': '0aaaaaaa', 'name': 'tvf_bias_point',          'range': (0, 127), 'display': 'MIDI note C1–C7'},
        {'offset': 0x1B, 'bits': '0000aaaa', 'name': 'tvf_bias_level',          'range': (0, 12),  'display': '-7 to +7'},  # OCR NOTE: 'o-wc7-m'
        {'offset': 0x1C, 'bits': '0aaaaaaa', 'name': 'tvf_env_depth',           'range': (0, 100)},
        {'offset': 0x1D, 'bits': '0aaaaaaa', 'name': 'tvf_env_velocity',        'range': (0, 100)},
        {'offset': 0x1E, 'bits': '00000aaa', 'name': 'tvf_env_depth_key_follow','range': (0, 4)},
        {'offset': 0x1F, 'bits': '00000aaa', 'name': 'tvf_env_time_key_follow', 'range': (0, 4)},
        {'offset': 0x20, 'bits': '0aaaaaaa', 'name': 'tvf_env_time_1',          'range': (0, 100)},
        {'offset': 0x21, 'bits': '0aaaaaaa', 'name': 'tvf_env_time_2',          'range': (0, 100)},
        {'offset': 0x22, 'bits': '0aaaaaaa', 'name': 'tvf_env_time_3',          'range': (0, 100)},
        {'offset': 0x23, 'bits': '0aaaaaaa', 'name': 'tvf_env_time_4',          'range': (0, 100)},
        {'offset': 0x24, 'bits': '0aaaaaaa', 'name': 'tvf_env_time_5',          'range': (0, 100)},
        {'offset': 0x25, 'bits': '0aaaaaaa', 'name': 'tvf_env_level_1',         'range': (0, 100)},
        {'offset': 0x26, 'bits': '0aaaaaaa', 'name': 'tvf_env_level_2',         'range': (0, 100)},
        {'offset': 0x27, 'bits': '0aaaaaaa', 'name': 'tvf_env_level_3',         'range': (0, 100)},
        {'offset': 0x28, 'bits': '0aaaaaaa', 'name': 'tvf_env_sus_level',       'range': (0, 100)},
        {'offset': 0x29, 'bits': '0aaaaaaa', 'name': 'tva_level',               'range': (0, 100)},
        {'offset': 0x2A, 'bits': '0aaaaaaa', 'name': 'tva_velocity',            'range': (0, 100)},
        {'offset': 0x2B, 'bits': '0aaaaaaa', 'name': 'tva_bias_point_1',        'range': (0, 127), 'display': 'MIDI note C1–C7'},
        {'offset': 0x2C, 'bits': '0000aaaa', 'name': 'tva_bias_level_1',        'range': (0, 12),  'display': '-7 to +7'},
        {'offset': 0x2D, 'bits': '0aaaaaaa', 'name': 'tva_bias_point_2',        'range': (0, 127), 'display': 'MIDI note C1–C7'},
        {'offset': 0x2E, 'bits': '0000aaaa', 'name': 'tva_bias_level_2',        'range': (0, 12),  'display': '-7 to +7'},
        {'offset': 0x2F, 'bits': '00000aaa', 'name': 'tva_env_time_key_follow', 'range': (0, 4)},
        {'offset': 0x30, 'bits': '00000aaa', 'name': 'tva_env_time_1_velo',     'range': (0, 4)},
        {'offset': 0x31, 'bits': '0aaaaaaa', 'name': 'tva_env_time_1',          'range': (0, 100)},
        {'offset': 0x32, 'bits': '0aaaaaaa', 'name': 'tva_env_time_2',          'range': (0, 100)},
        {'offset': 0x33, 'bits': '0aaaaaaa', 'name': 'tva_env_time_3',          'range': (0, 100)},
        {'offset': 0x34, 'bits': '0aaaaaaa', 'name': 'tva_env_time_4',          'range': (0, 100)},
        {'offset': 0x35, 'bits': '0aaaaaaa', 'name': 'tva_env_time_5',          'range': (0, 100)},
        {'offset': 0x36, 'bits': '0aaaaaaa', 'name': 'tva_env_level_1',         'range': (0, 100)},
        {'offset': 0x37, 'bits': '0aaaaaaa', 'name': 'tva_env_level_2',         'range': (0, 100)},
        {'offset': 0x38, 'bits': '0aaaaaaa', 'name': 'tva_env_level_3',         'range': (0, 100)},
        {'offset': 0x39, 'bits': '0aaaaaaa', 'name': 'tva_env_sus_level',       'range': (0, 100)},
    ],
}

TONE_PARAMS = {
    # Table 3 — 246 bytes total (common + 4 partials)
    '_total_size': 0x0178,  # 7-bit: 0x01*128 + 0x78 = 248... verify on device
    'common_offset':   0x00,
    'partial1_offset': 0x0E,
    'partial2_offset': 0x48,
    'partial3_offset': 0x82,    # OCR NOTE: shown as 0x102 in source; likely split-byte; verify
    'partial4_offset': 0xBC,    # OCR NOTE: shown as 0x13C in source; verify
    'common':  TONE_COMMON_PARAMS,
    'partial': TONE_PARTIAL_PARAMS,
}

PATCH_INTERNAL_MODE_GROUP = {
    # Table 6-2-2 — 2 bytes
    '_total_size': 0x02,
    'params': [
        {'offset': 0x00, 'bits': '00000aaa', 'name': 'tone_mode',
         'range': (0, 5), 'labels': ('1st', '2nd', 'single', 'dual', 'velo_switch', 'mix')},
        {'offset': 0x01, 'bits': '000000aa', 'name': 'tone_mode_sensitivity',
         'range': (0, 3), 'display': '1–4'},
    ],
}

PATCH_INTERNAL_TONE_GROUP = {
    # Table 6-2-3 — 9 bytes; same layout for 1st and 2nd tone groups
    '_total_size': 0x09,
    'params': [
        {'offset': 0x00, 'bits': '000000aa', 'name': 'tone_group',      'range': (0, 3),   'labels': ('a', 'b', 'i/c', 'l')},
        {'offset': 0x01, 'bits': '00aaaaaa', 'name': 'tone_number',     'range': (0, 63),  'display': '1–64'},
        {'offset': 0x02, 'bits': '0aaaaaaa', 'name': 'output_level',    'range': (0, 100)},
        {'offset': 0x03, 'bits': '00aaaaaa', 'name': 'panpot',          'range': (0, 14),  'display': 'L–R'},
        {'offset': 0x04, 'bits': '00aaaaaa', 'name': 'key_shift',       'range': (0, 48),  'display': '-24 to +24'},
        {'offset': 0x05, 'bits': '0aaaaaaa', 'name': 'fine_tune',       'range': (0, 100), 'display': '-50 to +50'},
        {'offset': 0x06, 'bits': '0000000a', 'name': 'chromatic_switch','range': (0, 1),   'labels': ('off', 'on')},
        {'offset': 0x07, 'bits': '0000000a', 'name': '_reserved'},
        {'offset': 0x08, 'bits': '0000000a', 'name': 'reverb_switch',   'range': (0, 1),   'labels': ('off', 'on')},
    ],
}

PATCH_EXTERNAL_GENERAL_GROUP = {
    # Table 6-3-2 — 6 bytes
    '_total_size': 0x06,
    'params': [
        {'offset': 0x00, 'bits': '000aaaaa', 'name': 'midi_channel',  'range': (0, 16),  'display': '1–16 or Off'},
        {'offset': 0x01, 'bits': '0000000a', 'name': 'midi_mode',     'range': (0, 1),   'labels': ('poly', 'mono')},
        {'offset': 0x02, 'bits': '0aaaaaaa', 'name': 'output_level',  'range': (0, 100)},
        {'offset': 0x03, 'bits': '0aaaaaaa', 'name': 'bender_range',  'range': (0, 24)},
        {'offset': 0x04, 'bits': '0000000a', 'name': '_reserved'},
        {'offset': 0x05, 'bits': '0xxxxxxx', 'name': '_reserved'},
    ],
}

PATCH_EXTERNAL_INDIVIDUAL_STRING = {
    # Table 6-3-4 — 3 bytes per string
    '_total_size': 0x03,
    'params': [
        {'offset': 0x00, 'bits': '0aaaaaaa', 'name': 'program_change_number', 'range': (0, 127), 'display': '1–128'},
        {'offset': 0x01, 'bits': '00aaaaaa', 'name': 'transpose',             'range': (0, 48),  'display': '-24 to +24'},
        {'offset': 0x02, 'bits': '0000000a', 'name': 'string_select',         'range': (0, 1),   'labels': ('off', 'on')},
    ],
}

PATCH_PARAMS = {
    # Table 6 — 188 bytes total
    '_total_size': 0x013C,
    'common_offset':   0x00,
    'internal_offset': 0x14,
    'external_offset': 0x78,

    'common': {
        # Table 6-1 — 20 bytes
        '_total_size': 0x14,
        'params': [
            {'offset': 0x00, 'bits': '0aaaaaaa', 'name': 'patch_name_1',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x01, 'bits': '0aaaaaaa', 'name': 'patch_name_2',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x02, 'bits': '0aaaaaaa', 'name': 'patch_name_3',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x03, 'bits': '0aaaaaaa', 'name': 'patch_name_4',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x04, 'bits': '0aaaaaaa', 'name': 'patch_name_5',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x05, 'bits': '0aaaaaaa', 'name': 'patch_name_6',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x06, 'bits': '0aaaaaaa', 'name': 'patch_name_7',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x07, 'bits': '0aaaaaaa', 'name': 'patch_name_8',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x08, 'bits': '0aaaaaaa', 'name': 'patch_name_9',  'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x09, 'bits': '0aaaaaaa', 'name': 'patch_name_10', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x0A, 'bits': '0aaaaaaa', 'name': 'patch_name_11', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x0B, 'bits': '0aaaaaaa', 'name': 'patch_name_12', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x0C, 'bits': '0aaaaaaa', 'name': 'patch_name_13', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x0D, 'bits': '0aaaaaaa', 'name': 'patch_name_14', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x0E, 'bits': '0aaaaaaa', 'name': 'patch_name_15', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x0F, 'bits': '0aaaaaaa', 'name': 'patch_name_16', 'range': (32, 127), 'display': 'ASCII'},
            {'offset': 0x10, 'bits': '00000aaa', 'name': 'reverb_type',   'range': (0, 7),    'display': '1–8'},
            {'offset': 0x11, 'bits': '00000aaa', 'name': 'reverb_time',   'range': (0, 7)},
            {'offset': 0x12, 'bits': '00000aaa', 'name': 'reverb_level',  'range': (0, 7)},
            {'offset': 0x13, 'bits': '000000aa', 'name': 'velocity_curve','range': (0, 3),    'display': '1–4'},
        ],
    },

    'internal': {
        # Table 6-2 — 120 bytes; 6 strings × 20 bytes each
        '_total_size': 0x78,
        # Within each string: mode_group at +0x00, 1st_tone at +0x02, 2nd_tone at +0x0B
        'string_offsets': [0x00, 0x14, 0x28, 0x3C, 0x50, 0x64],
        'mode_group_offset':    0x00,
        '1st_tone_group_offset': 0x02,
        '2nd_tone_group_offset': 0x0B,
        'mode_group': PATCH_INTERNAL_MODE_GROUP,
        'tone_group': PATCH_INTERNAL_TONE_GROUP,
    },

    'external': {
        # Table 6-3 — 48 bytes; 2 branches × 24 bytes each
        '_total_size': 0x30,
        'branch_offsets': {'A': 0x00, 'B': 0x18},
        # Within each branch: general_group at +0x00, individual_group at +0x06
        'general_group_offset':    0x00,
        'individual_group_offset': 0x06,
        # Individual group: 6 strings × 3 bytes at offsets 0x00/0x03/0x06/0x09/0x0C/0x0F
        'individual_string_offsets': [0x00, 0x03, 0x06, 0x09, 0x0C, 0x0F],
        'general_group':           PATCH_EXTERNAL_GENERAL_GROUP,
        'individual_string':       PATCH_EXTERNAL_INDIVIDUAL_STRING,
    },
}

SYSTEM_SETUP_PARAMS = {
    # Table 7 — 19 bytes
    '_total_size': 0x13,
    'params': [
        {'offset': 0x00, 'bits': '0aaaaaaa', 'name': 'master_tune',          'range': (0, 127), 'display': '435.6–446.2 Hz'},
        {'offset': 0x01, 'bits': '000aaaaa', 'name': 'control_channel',      'range': (0, 16),  'display': '1–16 or Off'},
        {'offset': 0x02, 'bits': '0000000a', 'name': 'display_mode',         'range': (0, 2)},
        {'offset': 0x03, 'bits': '000aaaaa', 'name': 'midi_cont_bender',     'range': (0, 24)},
        {'offset': 0x04, 'bits': '0000000a', 'name': 'midi_cont_modulation', 'range': (0, 1),   'labels': ('off', 'on')},
        {'offset': 0x05, 'bits': '0000000a', 'name': 'midi_cont_volume',     'range': (0, 1),   'labels': ('off', 'on')},
        {'offset': 0x06, 'bits': '00000aaa', 'name': 'gk2_s1_assign',        'range': (0, 4)},
        {'offset': 0x07, 'bits': '0000000a', 'name': 'gk2_s1_mode',          'range': (0, 1),   'labels': ('latch', 'unlatch')},
        {'offset': 0x08, 'bits': '00000aaa', 'name': 'gk2_s2_assign',        'range': (0, 4)},
        {'offset': 0x09, 'bits': '0000000a', 'name': 'gk2_s2_mode',          'range': (0, 1),   'labels': ('latch', 'unlatch')},
        {'offset': 0x0A, 'bits': '00000aaa', 'name': 'fc100_switch_assign',  'range': (0, 4)},
        {'offset': 0x0B, 'bits': '0000000a', 'name': 'fc100_switch_mode',    'range': (0, 1),   'labels': ('latch', 'unlatch')},
        {'offset': 0x0C, 'bits': '00000aaa', 'name': 'fc100_ev5_assign',     'range': (0, 4)},
        {'offset': 0x0D, 'bits': '00000aaa', 'name': 'string_sens_1',        'range': (0, 7),   'display': '1–8'},
        {'offset': 0x0E, 'bits': '00000aaa', 'name': 'string_sens_2',        'range': (0, 7),   'display': '1–8'},
        {'offset': 0x0F, 'bits': '00000aaa', 'name': 'string_sens_3',        'range': (0, 7),   'display': '1–8'},
        {'offset': 0x10, 'bits': '00000aaa', 'name': 'string_sens_4',        'range': (0, 7),   'display': '1–8'},
        {'offset': 0x11, 'bits': '00000aaa', 'name': 'string_sens_5',        'range': (0, 7),   'display': '1–8'},
        {'offset': 0x12, 'bits': '00000aaa', 'name': 'string_sens_6',        'range': (0, 7),   'display': '1–8'},
    ],
}

PART_SETTING_PARAMS = {
    # Table 8 — 8 bytes
    '_total_size': 0x08,
    'params': [
        {'offset': 0x00, 'bits': '0000000a', 'name': 'timbre_group',  'range': (0, 1),   'labels': ('internal', 'card')},
        {'offset': 0x01, 'bits': '0aaaaaaa', 'name': 'timbre_number', 'range': (0, 127), 'display': 'A-11 to B-88 / 1–128'},
        {'offset': 0x02, 'bits': '0aaaaaaa', 'name': 'output_level',  'range': (0, 100)},
        {'offset': 0x03, 'bits': '0000aaaa', 'name': 'panpot',        'range': (0, 14),  'display': 'left–right'},
        {'offset': 0x04, 'bits': '000aaaaa', 'name': 'midi_channel',  'range': (0, 16),  'display': '1–16 or Off'},
        {'offset': 0x05, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x06, 'bits': '0xxxxxxx', 'name': '_reserved'},
        {'offset': 0x07, 'bits': '0xxxxxxx', 'name': '_reserved'},
    ],
}

PATCH_CHAIN_PARAMS = {
    # Table 9 — 50 bytes; 25 steps × 2 bytes
    # Step 1 end_mark is always 0 (fixed). end_mark=1 terminates chain.
    '_total_size': 0x32,
    'step_offsets': [i * 2 for i in range(25)],  # 0x00, 0x02, 0x04 ... 0x30
    'step_params': [
        {'offset_in_step': 0x00, 'bits': '0000000a', 'name': 'end_mark',    'range': (0, 1),   'labels': ('step', 'end')},
        {'offset_in_step': 0x01, 'bits': '0aaaaaaa', 'name': 'patch_number','range': (0, 127), 'display': 'I-11 to C-88'},
    ],
}

DISPLAY_PARAMS = {
    # Table 4 — 32 bytes; write-only (no RQ1/RQD)
    # LCD is 2 rows × 16 ASCII chars
    '_total_size': 0x20,
    '_write_only': True,
    'upper_row_offsets': list(range(0x00, 0x10)),  # chars 1–16
    'lower_row_offsets': list(range(0x10, 0x20)),  # chars 1–16
}

WRITE_REQUEST_PARAMS = {
    # Table 5 — base address 0x40 0x00 0x00
    # Simulates the front-panel Write key.
    # Write Result is returned at [0x40, 0x10, 0x00].
    'tone_write_area_offsets': {
        # offset → which tone temporary area it targets
        0x00: 'tone_temp_1st_string1', 0x02: 'tone_temp_2nd_string1',
        0x04: 'tone_temp_1st_string2', 0x06: 'tone_temp_2nd_string2',
        0x08: 'tone_temp_1st_string3', 0x0A: 'tone_temp_2nd_string3',
        0x0C: 'tone_temp_1st_string4', 0x0E: 'tone_temp_2nd_string4',
        0x10: 'tone_temp_1st_string5', 0x12: 'tone_temp_2nd_string5',
        0x14: 'tone_temp_1st_string6', 0x16: 'tone_temp_2nd_string6',
        0x18: 'tone_temp_part1',       0x1A: 'tone_temp_part2',
    },
    'tone_write_target': {
        # Table 5-1 — 2 bytes appended to each tone write offset
        '_total_size': 0x02,
        'params': [
            {'offset': 0x00, 'bits': '00aaaaaa', 'name': 'tone_number', 'range': (0, 63), 'display': '01–64'},
            {'offset': 0x01, 'bits': '0000000a', 'name': 'tone_bank',   'range': (0, 1),  'labels': ('internal', 'card')},
        ],
    },
    'timbre_write_area_offsets': {
        0x0100: 'timbre_temp_part1_string1', 0x0102: 'timbre_temp_part2_string1',
        0x0104: 'timbre_temp_part1_string2', 0x0106: 'timbre_temp_part2_string2',
        0x0108: 'timbre_temp_part1_string3', 0x010A: 'timbre_temp_part2_string3',
        0x010C: 'timbre_temp_part1_string4', 0x010E: 'timbre_temp_part2_string4',
    },
    'timbre_write_target': {
        # Table 5-2 — 2 bytes
        '_total_size': 0x02,
        'params': [
            {'offset': 0x00, 'bits': '0aaaaaaa', 'name': 'timbre_number', 'range': (0, 127), 'display': 'A-11 to B-88 / 1–128'},
            {'offset': 0x01, 'bits': '0000000a', 'name': 'timbre_bank',   'range': (0, 1),   'labels': ('internal', 'card')},
        ],
    },
    'patch_write_area_offset': 0x0400,
    'patch_write_target': {
        # Table 5-3 — 2 bytes
        '_total_size': 0x02,
        'params': [
            {'offset': 0x00, 'bits': '00aaaaaa', 'name': 'patch_number', 'range': (0, 63), 'display': '11–88 / 1–64 or 65–128'},
            {'offset': 0x01, 'bits': '0000000a', 'name': 'patch_bank',   'range': (0, 1),  'labels': ('internal', 'card')},
        ],
    },
}

WRITE_RESULT_PARAMS = {
    # Table 5-4 — 1 byte at [0x40, 0x10, 0x00]
    '_total_size': 0x01,
    'params': [
        {'offset': 0x00, 'bits': '000000aa', 'name': 'result', 'range': (0, 3),
         'labels': ('function_completed', 'card_not_ready', 'write_protected', 'reserved')},
    ],
}


# ---------------------------------------------------------------------------
# Parameter base address table (Table A)
# Each address is [MSB, MID, LSB] in 7-bit hex.
# ---------------------------------------------------------------------------

PARAMETER_BASE_ADDRESSES = {

    # --- Timbre Temporary (8 slots: 4 strings × 2 parts each) ---
    # Table 1; stride 0x10 between entries
    'timbre_temporary': [
        {'address': [0x03, 0x00, 0x00], 'description': 'Timbre Temporary string 1 part 1', 'params': TIMBRE_TEMPORARY_PARAMS},
        {'address': [0x03, 0x00, 0x10], 'description': 'Timbre Temporary string 1 part 2', 'params': TIMBRE_TEMPORARY_PARAMS},
        {'address': [0x03, 0x00, 0x20], 'description': 'Timbre Temporary string 2 part 1', 'params': TIMBRE_TEMPORARY_PARAMS},
        {'address': [0x03, 0x00, 0x30], 'description': 'Timbre Temporary string 2 part 2', 'params': TIMBRE_TEMPORARY_PARAMS},  # OCR NOTE: appeared as 0x20 twice; corrected by stride
        {'address': [0x03, 0x00, 0x40], 'description': 'Timbre Temporary string 3 part 1', 'params': TIMBRE_TEMPORARY_PARAMS},
        {'address': [0x03, 0x00, 0x50], 'description': 'Timbre Temporary string 3 part 2', 'params': TIMBRE_TEMPORARY_PARAMS},
        {'address': [0x03, 0x00, 0x60], 'description': 'Timbre Temporary string 4 part 1', 'params': TIMBRE_TEMPORARY_PARAMS},
        {'address': [0x03, 0x00, 0x70], 'description': 'Timbre Temporary string 4 part 2', 'params': TIMBRE_TEMPORARY_PARAMS},
    ],

    # --- Rhythm Setup Temporary (85 notes C1–C8, stride 0x04) ---
    # Table 2; first and last entries shown; fill intermediates by stride
    'rhythm_setup_temporary': [
        {'address': [0x03, 0x01, 0x10], 'description': 'Rhythm Setup Temporary  1 (C1)',  'params': RHYTHM_SETUP_PARAMS},
        {'address': [0x03, 0x01, 0x14], 'description': 'Rhythm Setup Temporary  2 (C#1)', 'params': RHYTHM_SETUP_PARAMS},
        # ... stride 0x04; fill with:
        # [0x03, 0x01, 0x10 + n*4] for n in range(85), with 7-bit carry into MID byte
        {'address': [0x03, 0x02, 0x5C], 'description': 'Rhythm Setup Temporary 84 (B7)',  'params': RHYTHM_SETUP_PARAMS},
        {'address': [0x03, 0x02, 0x60], 'description': 'Rhythm Setup Temporary 85 (C8)',  'params': RHYTHM_SETUP_PARAMS},
    ],

    # --- Tone Temporary (12 string slots + 2 part slots; stride 0x01:0x76 between pairs) ---
    # Table 3; OCR NOTE: several MSB digits were garbled; corrected by stride arithmetic
    'tone_temporary': [
        {'address': [0x04, 0x00, 0x00], 'description': 'Tone Temporary 1st of string 1', 'params': TONE_PARAMS},
        {'address': [0x04, 0x01, 0x76], 'description': 'Tone Temporary 2nd of string 1', 'params': TONE_PARAMS},
        {'address': [0x04, 0x03, 0x6C], 'description': 'Tone Temporary 1st of string 2', 'params': TONE_PARAMS},  # OCR NOTE: LSB truncated; inferred from stride
        {'address': [0x04, 0x05, 0x62], 'description': 'Tone Temporary 2nd of string 2', 'params': TONE_PARAMS},
        {'address': [0x04, 0x07, 0x58], 'description': 'Tone Temporary 1st of string 3', 'params': TONE_PARAMS},
        {'address': [0x04, 0x09, 0x4E], 'description': 'Tone Temporary 2nd of string 3', 'params': TONE_PARAMS},  # OCR NOTE: MSB was '108'; corrected to 0x04
        {'address': [0x04, 0x0B, 0x44], 'description': 'Tone Temporary 1st of string 4', 'params': TONE_PARAMS},
        {'address': [0x04, 0x0D, 0x3A], 'description': 'Tone Temporary 2nd of string 4', 'params': TONE_PARAMS},
        {'address': [0x04, 0x0F, 0x30], 'description': 'Tone Temporary 1st of string 5', 'params': TONE_PARAMS},
        {'address': [0x04, 0x11, 0x26], 'description': 'Tone Temporary 2nd of string 5', 'params': TONE_PARAMS},
        {'address': [0x04, 0x13, 0x1C], 'description': 'Tone Temporary 1st of string 6', 'params': TONE_PARAMS},  # OCR NOTE: LSB inferred from stride
        {'address': [0x04, 0x15, 0x12], 'description': 'Tone Temporary 2nd of string 6', 'params': TONE_PARAMS},
        {'address': [0x04, 0x17, 0x08], 'description': 'Tone Temporary part 1',          'params': TONE_PARAMS},
        {'address': [0x04, 0x18, 0x7E], 'description': 'Tone Temporary part 2',          'params': TONE_PARAMS},  # OCR NOTE: 'TE' → 0x7E
    ],

    # --- Timbre Memory (128 timbres, stride 0x08) ---
    # Table 1a
    'timbre_memory': [
        {'address': [0x05, 0x00, 0x00], 'description': 'Timbre Memory   1 (I-1   / I-A11)', 'params': TIMBRE_MEMORY_PARAMS},
        {'address': [0x05, 0x00, 0x08], 'description': 'Timbre Memory   2 (I-2   / I-A12)', 'params': TIMBRE_MEMORY_PARAMS},
        # ... stride 0x08 per timbre; 7-bit carry into MID byte after 0x78
        {'address': [0x05, 0x07, 0x70], 'description': 'Timbre Memory 127 (I-127 / I-B87)', 'params': TIMBRE_MEMORY_PARAMS},
        {'address': [0x05, 0x07, 0x78], 'description': 'Timbre Memory 128 (I-128 / I-B88)', 'params': TIMBRE_MEMORY_PARAMS},
    ],

    # --- Tone Memory (64 tones, stride 0x02:0x00 = 256 bytes) ---
    # Table 3
    'tone_memory': [
        {'address': [0x08, 0x00, 0x00], 'description': 'Tone Memory  1 (i01)', 'params': TONE_PARAMS},
        {'address': [0x08, 0x02, 0x00], 'description': 'Tone Memory  2 (i02)', 'params': TONE_PARAMS},
        # ... stride [0x00, 0x02, 0x00] per tone
        {'address': [0x08, 0x7C, 0x00], 'description': 'Tone Memory 63 (i63)', 'params': TONE_PARAMS},
        {'address': [0x08, 0x7E, 0x00], 'description': 'Tone Memory 64 (i64)', 'params': TONE_PARAMS},
    ],

    # --- Rhythm Setup Memory (85 notes, stride 0x04) ---
    # Table 2
    'rhythm_setup_memory': [
        {'address': [0x09, 0x00, 0x00], 'description': 'Rhythm Setup Memory  1 (C1)',  'params': RHYTHM_SETUP_PARAMS},
        {'address': [0x09, 0x00, 0x04], 'description': 'Rhythm Setup Memory  2 (C#1)', 'params': RHYTHM_SETUP_PARAMS},
        # ... stride 0x04
        {'address': [0x09, 0x02, 0x4C], 'description': 'Rhythm Setup Memory 84 (B7)',  'params': RHYTHM_SETUP_PARAMS},
        {'address': [0x09, 0x02, 0x50], 'description': 'Rhythm Setup Memory 85 (C8)',  'params': RHYTHM_SETUP_PARAMS},
    ],

    # --- Display (write-only) ---
    'display': {
        'address': [0x20, 0x00, 0x00],
        'description': 'LCD Display (write-only via DT1; no RQ1/RQD)',
        'params': DISPLAY_PARAMS,
    },

    # --- Write Request / Write Result ---
    'write_request': {
        'address': [0x40, 0x00, 0x00],
        'description': 'Write Request (simulates front-panel Write key)',
        'params': WRITE_REQUEST_PARAMS,
    },
    'write_result': {
        'address': [0x40, 0x10, 0x00],
        'description': 'Write Result (read back after write request)',
        'params': WRITE_RESULT_PARAMS,
    },

    # --- Patch Temporary ---
    'patch_temporary': {
        'address': [0x50, 0x00, 0x00],
        'description': 'Patch Temporary area',
        'params': PATCH_PARAMS,
    },

    # --- Patch Memory (128 patches, stride 0x013C = 188 bytes) ---
    # Table 6; internal bank = 1-64, card bank = 65-128
    'patch_memory': [
        {'address': [0x51, 0x00, 0x00], 'description': 'Patch Memory   1 (1/I-11)',  'params': PATCH_PARAMS},
        {'address': [0x51, 0x01, 0x3C], 'description': 'Patch Memory   2 (2/I-12)',  'params': PATCH_PARAMS},
        # ... stride 188 bytes (0x01:0x3C in 7-bit) per patch
        {'address': [0x51, 0x50, 0x08], 'description': 'Patch Memory  63 (63/I-87)', 'params': PATCH_PARAMS},
        {'address': [0x51, 0x5C, 0x44], 'description': 'Patch Memory  64 (64/I-88)', 'params': PATCH_PARAMS},
        # Card patches 65-128 follow; addresses continue from 0x51 with same stride
    ],

    # --- System Setup ---
    'system_setup': {
        'address': [0x52, 0x00, 0x00],
        'description': 'System Setup',
        'params': SYSTEM_SETUP_PARAMS,
    },

    # --- Part Settings (3: part1, part2, partR) ---
    'part_setting': [
        {'address': [0x52, 0x01, 0x00], 'description': 'Part Setting part 1 (guitar synth)',   'params': PART_SETTING_PARAMS},
        {'address': [0x52, 0x01, 0x08], 'description': 'Part Setting part 2 (guitar synth)',   'params': PART_SETTING_PARAMS},
        {'address': [0x52, 0x01, 0x10], 'description': 'Part Setting part R (rhythm)',          'params': PART_SETTING_PARAMS},
    ],

    # --- Patch Chains (5 chains labelled 1A–1E) ---
    'patch_chain': [
        {'address': [0x52, 0x02, 0x00], 'description': 'Patch Chain 1 (1A)', 'params': PATCH_CHAIN_PARAMS},
        {'address': [0x52, 0x02, 0x32], 'description': 'Patch Chain 2 (1B)', 'params': PATCH_CHAIN_PARAMS},
        {'address': [0x52, 0x02, 0x64], 'description': 'Patch Chain 3 (1C)', 'params': PATCH_CHAIN_PARAMS},
        {'address': [0x52, 0x03, 0x16], 'description': 'Patch Chain 4 (1D)', 'params': PATCH_CHAIN_PARAMS},
        {'address': [0x52, 0x03, 0x48], 'description': 'Patch Chain 5 (1E)', 'params': PATCH_CHAIN_PARAMS},
    ],
}


# ---------------------------------------------------------------------------
# Helper: 7-bit address arithmetic
# ---------------------------------------------------------------------------

def _flat(addr):
    """Convert 3-byte 7-bit address to a flat integer."""
    return addr[0] * 128 * 128 + addr[1] * 128 + addr[2]

def _from_flat(n):
    """Convert flat integer back to 3-byte 7-bit address."""
    lsb = n % 128;       n //= 128
    mid = n % 128;       msb = n // 128
    return [msb, mid, lsb]

def addr_add(base, offset):
    """Add a flat integer offset to a 3-byte 7-bit address [MSB, MID, LSB].
    Uses proper 7-bit carry: each byte is 0x00–0x7F, MSB overflows silently."""
    return _from_flat(_flat(base) + offset)


def checksum(data):
    """Roland checksum: (-sum(data)) & 0x7F"""
    return (-sum(data)) & 0x7F


def build_rq1(device_id, address, size):
    """Build a one-way data request (RQ1) message."""
    body = address + list(size) if isinstance(size, (list, tuple)) else address + [0x00, 0x00, size]
    return bytes([0xF0, 0x41, device_id, 0x16, 0x11] + body + [checksum(body), 0xF7])


def build_dt1(device_id, address, data):
    """Build a one-way data set (DT1) message.
    Splits automatically at 256-byte payload limit."""
    messages = []
    for i in range(0, len(data), 256):
        chunk = data[i:i+256]
        body  = addr_add(address, i) + list(chunk)
        messages.append(bytes([0xF0, 0x41, device_id, 0x16, 0x12] + body + [checksum(body), 0xF7]))
    return messages


if __name__ == '__main__':
    # Quick sanity checks
    # Tone temporary stride = 246 bytes (= TONE_PARAMS total size)
    assert addr_add([0x04, 0x00, 0x00], 246) == [0x04, 0x01, 0x76], addr_add([0x04, 0x00, 0x00], 246)
    assert addr_add([0x04, 0x01, 0x76], 246) == [0x04, 0x03, 0x6C], addr_add([0x04, 0x01, 0x76], 246)
    assert addr_add([0x04, 0x03, 0x6C], 246) == [0x04, 0x05, 0x62], addr_add([0x04, 0x03, 0x6C], 246)
    # Checksum: body = addr + size; (-sum) & 0x7F
    assert checksum([0x50, 0x00, 0x00, 0x00, 0x01, 0x3C]) == (-(0x50 + 0x01 + 0x3C)) & 0x7F

    print('GR-50 parameter map loaded.')
    print(f'  Tone partial params : {len(TONE_PARTIAL_PARAMS["params"])}')
    print(f'  Tone common params  : {len(TONE_COMMON_PARAMS["params"])}')
    print(f'  Patch common params : {len(PATCH_PARAMS["common"]["params"])}')
    print(f'  System setup params : {len(SYSTEM_SETUP_PARAMS["params"])}')
    print(f'  Patch chain steps   : {len(PATCH_CHAIN_PARAMS["step_offsets"])}')
