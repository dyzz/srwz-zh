# SRWZ shared text layout

Pure ESM shared by browser and Node callers. `engine.mjs` has no DOM, filesystem, process or font-measurement dependency. Encoding, source binding, resource capacity and ISO writeback remain resource-owner responsibilities.

## Scene contracts

| Scene | Step | Total width | Native rows |
|---|---:|---:|---:|
| story | 21px | 483px / 23 cells | 3 |
| battle | 22px | 462px / 21 cells | 2 |
| main_flow / sp_flow | 16px | 480px / 30 cells | owner budget |
| main_scroll | 24px | 528px / 22 cells | owner budget |
| main_scroll_strip | 24px | 504px / 21 cells | owner budget |
| sp_scroll | 25px | 575px / 23 cells | owner budget |
| library_character | 21px | 336px / 16 cells | owner budget |
| library_robot | 21px | 546px / 26 cells | owner budget |
| library_glossary | 21px | 525px / 25 cells | owner budget |

Story and battle continuation rows contain one ideographic-space indent. Quotes and indentation consume the total width. The last glyph's overhang also counts. Battle preserves input row count by default; changing it requires an explicit timing decision. Prose preserves paragraphs and blank separators, permits word splitting and balances physical widths within the minimum feasible row count. Different paragraph lengths need not produce equal widths.

`summary/03/000` and `summary/04/000` select the narrow scroll scene through `options.resourceId`. Compact scopes use each scene's own width, height, step and complete restoration; native height10 is encoded as 8A. Keep unsupported dynamic templates, independent choices, aligned cards and fixed grids with their explicit owners.

## API

```js
import {layout, measure, validate, expandCompact} from './engine.mjs';
const result = layout('“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后返回基地！”',
  'battle', {preserveLineCount:false});
// Widths 446 / 198px, including the second-row indent.
```

`layout` reflows; `measure` preserves stored rows; `validate` checks geometry and line rules; `expandCompact` compiles author scopes. `height` is the native parameter, not doubled screen pixels. Pass `escapedNewlines:true` for literal backslash-n corpus notation. Use `keywordLinks:true` only for source-bound STAGE keyword streams. `maxLines` can tighten an owner budget but cannot expand the story/battle limit. Use `packing:'max_width'` only when explicitly requesting front-to-back fill instead of the prose default `balanced_width`.

The JSONL CLI accepts one request or a request array on each stdin line and returns `{ok:true,result}` / `{ok:false,error}`. Python callers use `srwz.js_layout.request_layout` or `layout_batch`; `SRWZ_NODE` selects the Node executable. No other layout implementation is silently substituted on failure.

## Generation and verification

```sh
python3 tools/text_layout/export_js_contracts.py --check
node --test shared/text-layout/engine.test.mjs
python3 -m unittest discover -s tests -p test_js_layout_adapter.py
```

`contracts.mjs` is generated from the Python scene profiles, compact metrics, control protocol, word lists and `config/text-layout/native-scene-contracts.json`. Its source hashes detect drift. Width provenance is recorded in `docs/issue-assets/shared-js-layout-20261028/prose-width-evidence.json`; LRPS2 mixed-glyph fixtures are in `docs/issue-assets/mixed-compact-20261028/evidence.json`. Static tests do not constitute a new ISO or LRPS2 acceptance.

Production adapters live in `tools/srwz/build_layout.py`. Shared runtime bytes belong in edition input snapshots and component fingerprints. Ordinary stored dialogue must be checked without silently rewriting it; source structure, timing, byte budgets and readback remain separate gates.
