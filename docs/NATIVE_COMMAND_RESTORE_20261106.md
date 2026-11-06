# Standalone COMMAND restored, 2026-11-06

User request: “指令我们不汉化了，其他指令保留”.

Original, The Best and Special Disc now use the original English COMMAND heading for the standalone unit command menu. The retired Chinese allocation is restored to its original blank pixels (original/best page 3, 180,235,28,17; SP page 8, 129,223,38,20). The full native drawing records, including size/position/UV and shadow, are restored. OTHERS COMMAND / 其他指令, selection/sort, and all other localized cells are unchanged.

The source recipe, component locks and validation manifest were refreshed. Regression suites for menu restore, UI headings, SP command headings, frame UV and SP title atlas passed: 31 tests.

Static ISO evidence: `issue-assets/native-command-20261106/candidates.json`. All three candidates were byte-compared against their current baseline: only KVMDATA/KVPDATA member ranges changed, sizes and LBAs unchanged. Standalone records match the source Japanese disc exactly; other drawing bytes unchanged. Current ISO promotion is recorded in `issue-assets/native-command-20261106/promotion.json`; pre-change images are APFS clones in `build/iso/native-command-20261106/*-before.iso`.

ARMSX2-runner evidence: Metal 4x, original candidate, `issue-assets/native-command-20261106/original-command.png`. Visually reviewed unit action menu displays COMMAND above 移动/攻击/阵型/精神/能力. Input reproduction: boot 1800 frames; start+180; down+60 twice; circle+500; R1+100; circle+100. Source card: `work/verification/spirit-cost-production-20261010/best-cold/save/current-best.ps2`. Runner copies the card per session. Additional SP setup/help captures are regression observations only, not proof of the changed SP battle command heading.

No separate The Best or SP standalone battle-command runtime proof, and no PCSX2/manual evidence claimed. Other-command preservation is backed by static pixel/drawing comparison rather than a new runtime screenshot of that menu.
