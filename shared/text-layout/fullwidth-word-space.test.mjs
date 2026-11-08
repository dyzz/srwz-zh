import test from 'node:test';
import assert from 'node:assert/strict';
import {measure, center, layout} from './proportional.mjs';
import {proportionalMetrics} from './proportional-metrics.mjs';

test('fullwidth word spaces share measurement, centering and reflow metrics', () => {
 for (const scene of ['story', 'main_scroll', 'main_flow', 'library_character', 'sp_flow']) {
  const profile = proportionalMetrics.profiles[scene];
  for (const text of ['THE　HEAT', 'Side　3', 'RX　78', 'CIWS　/　RX-78']) {
   const row = measure(text, scene).rows[0];
   assert.ok(row.glyphs.filter(g => g.text === '　').every(g => g.advance === profile.space.advance));
   assert.equal(center(text, scene).rows[0].advancePx, row.advancePx);
   const result = layout(text, scene);
   assert.equal(result.text, text);
   assert.equal(result.rows[0].advancePx, row.advancePx);
  }
 }
});
test('fullwidth indentation, Chinese gaps and repeated spaces keep native advance', () => {
 for (const scene of ['story', 'main_scroll', 'main_flow', 'library_character', 'sp_flow']) {
  const native = measure('甲　乙', scene).rows[0].glyphs.find(g => g.text === '　').advance;
  for (const text of ['　THE', 'THE　', 'THE　　HEAT', 'THE　中文', 'THE\n　HEAT']) {
   const spaces = measure(text, scene).rows.flatMap(r => r.glyphs).filter(g => g.text === '　');
   assert.ok(spaces.every(g => g.advance === native), `${scene}: ${text}`);
  }
 }
});
