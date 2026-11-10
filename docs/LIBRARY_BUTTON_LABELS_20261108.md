# Clear encyclopedia expression/voice labels, 2026-11-08

The supplied “○：表情 □：台词” screenshot showed heavy cyan overlapping strokes. These are dynamic font strings, not localized atlas rectangles. SP trace captured their source strings at 0x4B03D8 and 0x4B03E0, called from 0x216940 and 0x216990. Hiding those strings in temporary RAM removed all corresponding text, leaving the button sprites intact.

The shared call at SP 0x2168E8 invokes the native effect helper 0x209A40 with a0=2. That helper sets shear and enables faux-bold duplication. Retargeting only this call to the existing reset helper 0x209A70 eliminates the duplicated/tilted strokes. The following native reset remains unchanged. Font pixels, character codes, colors, geometry and advance are untouched.

Edition-specific file offsets: Original 0x1135C8, Best 0x113988, SP 0x117268. Each patch validates the exact call and the next 168 bytes of original context, including the closing reset. The implementation is `tools/srwz/library_button_labels.py`; all three build paths apply it and Best/SP readback verifies it. The Best projector excludes the Original call before applying its own edition-specific call.

Validation:

- 3 new patch tests, 12 Best backend tests, 4 optical-metric tests, and 2 non-Unicorn body-metric tests passed (21 total). Edited Python modules compile; diff whitespace check passed.
- The optional Unicorn body-metric execution test aborted the system Python process (exit 132). It is not counted as passed. The two non-Unicorn body tests were run separately and passed. Full repository suite not run.
- All three candidates were fully byte-compared with their baseline current ISOs: changes are confined to the four-byte callsite (one byte differs), unchanged member sizes and LBAs, and identical bytes elsewhere. Promotion records preserve before/after hashes and APFS backup paths.
- ARMSX2-runner Metal 4x: initial state-load/RAM experiment isolated the cause; SP candidate subsequently cold-booted from ISO, navigated Title → Library → Characters → first character, and displayed the clear labels without RAM patches. `sp-cold.png` is that cold-boot evidence. No separate Original/Best runtime or PCSX2/manual evidence claimed.
- `comparison.png`: upper strip is the reproduced baseline; lower strip is the SP cold-boot candidate. Both use the same screenshot crop without rescaling. The character pages differ, but the label positions/metrics are unchanged.

Current ISO promotion is recorded in `issue-assets/library-button-labels-20261108/promotion.json`. Unrelated in-progress typography candidates were not rewritten; they pick up this change on their next build through the integrated build paths.
