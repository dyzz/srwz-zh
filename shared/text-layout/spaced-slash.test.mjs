import test from 'node:test';
import assert from 'node:assert/strict';
import {measure,center,layout} from './proportional.mjs';
test('identifier slash and optional single spaces share proportional measurement',()=>{
 for(const scene of ['story','main_scroll','library_character','sp_flow']){
  const opt={spacedSlash:true};
  const compact=measure('CIWS/RX-78',scene,opt).rows[0];
  const spaced=measure('CIWS / RX-78',scene,opt).rows[0];
  const spaces=spaced.glyphs.filter(g=>g.text.trim()==='');
  assert.equal(spaces.length,2);
  assert.equal(spaced.advancePx-compact.advancePx,spaces.reduce((s,g)=>s+g.advance,0));
  assert.equal(spaced.glyphs.find(g=>g.text==='/').advance,compact.glyphs.find(g=>g.text==='/').advance);
  assert.equal(center('CIWS / RX-78',scene,100,opt).rows[0].advancePx,spaced.advancePx);
  assert.ok(!layout('CIWS / RX-78',scene,opt).compiledText.includes('<z>'));
 }
});
test('slash handling preserves CJK gaps, repeated spaces and indentation',()=>{
 for(const text of ['中文 / 中文','CIWS  /  RX','　CIWS','/ RX','CIWS /'])
  assert.deepEqual(measure(text,'story',{spacedSlash:true}).rows,measure(text,'story').rows);
 assert.equal(measure('A/B/C','story',{spacedSlash:true}).rows[0].advancePx,measure('A/B/C','story').rows[0].advancePx);
 assert.equal(measure('ＣＩＷＳ　／　ＲＸ-７８','story',{spacedSlash:true}).rows[0].advancePx,measure('CIWS / RX-78','story',{spacedSlash:true}).rows[0].advancePx);
});
