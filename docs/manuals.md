# Synth manuals used for the adaptations

The parameter maps in some adaptations were built from the vendors' own manuals. The PDFs are not kept in
this repository: the vendors own them, and they are free to download again from the links below. Save them
in the repository root if you need them; `*.pdf` files there are ignored by git.

Where the manuals and real dumps disagree, the real dumps won. Those cases are noted below and in the
adaptations' comments.

## Roland D-50 — `adaptations/RolandD50.py`

| Document | Link |
|---|---|
| D-50 MIDI Implementation | <https://cdn.roland.com/assets/media/pdf/D-50_MI.pdf> |
| D-50 Owner's Manual | <https://cdn.roland.com/assets/media/pdf/D-50_OM.pdf> |

Both are listed in Roland's US manual archive, <https://www.roland.com/us/support/manual_archive/>. Roland's
global product pages have no D-50 manuals.

- The MIDI Implementation is a scan without a text layer. The parameter tables are on PDF pages 10 and 11:
  *4-4 partial block, *4-5 common block, *4-6 patch block.
- The common block's offset 39 is labelled "Low EQ Frequency" in the manual, but its values (250 Hz to 9.5 kHz)
  are the high EQ's. The adaptation calls it "High EQ frequency".
- Checked against the "Digital Dreams" bank in `adaptations/testData/Roland_D50`: every value of all 64 patches
  lies in the manual's ranges (`adaptations/test_RolandD50.py`).

## Korg 03R/W — `adaptations/Korg_03RW.py`

| Document | Link |
|---|---|
| 03R/W Owner's Manual | <https://www.korg.com/us/support/download/product/1/372/> |
| 01/W FD / 01/W Owner's Manual | <https://www.korg.com/us/support/download/product/1/1/> ("Owner's Manual") |

Korg publishes no MIDI implementation for the 03R/W, and its owner's manual has only the MIDI implementation
chart. The program layout comes from the 01/W family instead:

- The 01/W owner's manual is a scan. Its MIDI Implementation starts on manual page 199. The PROGRAM PARAMETER
  table (TABLE 1) and its notes are on manual page 206 (PDF page 211). A program is 172 bytes, as on the 03R/W.
- Checked against the 03R/W bank in `adaptations/testData/Korg_03RW` (`vicbank1.syx`): every value of all
  100 programs lies in TABLE 1's ranges (`adaptations/test_Korg_03RW.py`).
- TABLE 1 writes the multisound bytes as "0, 1~FF : OFF, 0~254". Real programs store the multisound number
  itself ("Saw Solo" uses 245 = Saw, "Square?" 247 = Square, "Trumpet X" 112 = Trumpet), so FF is OFF.
- The multisound names come from the "Multi Sound Name" list on the last page (PDF page 140) of the 03R/W
  owner's manual, which is also a scan.
- The 03R/W has no wave shaping: those bytes (82-86 and 133-137) hold "off" in every real program. The
  adaptation neither shows nor writes them, nor the effect parameters (bytes 143-171).

## Roland GR-50 — `adaptations/Roland_GR50.py`

| Document | Link |
|---|---|
| GR-50 Owner's Manual | <https://cdn.roland.com/assets/media/pdf/GR-50_OM.pdf> |

Listed in Roland's US manual archive. The parameter tables from it are transcribed in `gr50_params.py`.

## Roland U-20 / U-220 — `adaptations/Roland_U20_U220.py`

| Document | Link |
|---|---|
| U-220 Owner's Manual | <https://cdn.roland.com/assets/media/pdf/U-220_OM.pdf> |
| U-20 Owner's Manual | <https://cdn.roland.com/assets/media/pdf/U-20_OM.pdf> |

Listed in Roland's US manual archive. The U-220 owner's manual includes Roland's MIDI implementation from about
page 139. No parameter grid has been built from it yet.

## Behringer BCR2000 — `The-Orm/BCR2000FrontPanel.*`, `The-Orm/KnobPages.*`

The user manual (`BCF2000_BCR2000_M_EN.pdf`) explains the front panel. Its item (9) is the four assignable keys
at the lower right, which turn the grid's pages; item (8) is the PRESET keys, which recall the BCR2000's own
presets. The BCL details (encoder and button numbers, `.fkeys off`) come from the existing BCR2000 code and
testing on the hardware.
