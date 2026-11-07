# OTHERS COMMAND restored, 2026-11-07

Request: restore “其他指令” to the original English OTHERS COMMAND. This supersedes the 2026-11-06 decision to retain that particular Chinese heading.

Original and The Best: restore the native page 4 rectangle (40,232,215,23), and both complete native heading draw records in chunk 204. The full chunk is byte-identical to the source disc. ITEM / 项目 previously borrowed pixels inside COMMAND, so its unchanged 46×20 indexed pixels move to the retired OTHERS allocation on page 3 (132,235). Its drawing geometry and material are unchanged; only its texture page and UV change. Standalone COMMAND remains native, and other translations remain in place.

Special Disc already has native OTHERS COMMAND: current records at 36832 and 36866, plus every pixel sampled by their UV rectangles, match its Japanese source disc. No SP ISO mutation was necessary.

Build evidence: standard UI heading builder completed and refreshed the validation manifest. Menu restore, UI headings, frame UV, SP command headings and SP title atlas suites passed (31 tests). Candidate ISOs were fully compared against their previous current images: only the two KVM/KVP member ranges changed, with unchanged sizes/LBAs and unchanged bytes outside those ranges. APFS backups retain each previous current image. Promotion hashes are in `issue-assets/native-others-command-20261107/promotion.json`.

Runtime evidence: original and The Best candidates were cold-booted in ARMSX2-runner, Metal 4×. Both spirit selection screens were visually reviewed and show gold OTHERS / COMMAND. Captures are `issue-assets/native-others-command-20261107/original.png` and `best.png`; reproduction is `runtime.py` in the same folder. The small dash before OTHERS is native. No fresh SP runtime or PCSX2/manual verification is claimed. ITEM preservation is checked at indexed-pixel and drawing-record level.

The local full texture comparison gallery has been refreshed for pages 3 and 4. Historical diagrams and reports remain historical snapshots.
