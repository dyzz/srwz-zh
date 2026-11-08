import test from 'node:test';
import assert from 'node:assert/strict';
import {measure,center} from './proportional.mjs';
test('term list uses proportional Latin, native 18px Han, and fullwidth word spaces',()=>{
 for(const [text,width] of [['Side　3',54],['Evidence　01',101],['LOGOS',62],['PLANT评议会议长',150]]){
  const r=measure(text,'keyword_list').rows[0];assert.equal(r.advancePx,width);
  assert.equal(center(text,'keyword_list').rows[0].originX,-Math.trunc(width/2));
  assert.ok(r.glyphs.filter(g=>/^[评议会长]$/.test(g.text)).every(g=>g.advance===18&&g.width===18&&g.height===12));
  assert.ok(r.glyphs.filter(g=>g.text==='　').every(g=>g.advance===5));
 }
});
