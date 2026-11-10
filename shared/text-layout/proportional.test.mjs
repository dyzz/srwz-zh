import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {measure,center,layout,migrateCompact} from './proportional.mjs';
import {measure as legacyMeasure} from './engine.mjs';

test('tag-free measurement reproduces recorded ARMSX2 Side 3 draw geometry',()=>{
 const proof=JSON.parse(readFileSync(new URL('./fixtures/proportional-side3.json',import.meta.url)));
 const measured=measure(proof.text,'main_scroll');
 assert.equal(measured.fontSha256,proof.fontSha256);
 assert.deepEqual(measured.rows[0].glyphs.map(g=>[g.x,g.width,g.height]),proof.glyphs.map(g=>[g.x,g.width,g.height]));
 assert.equal(measured.rows[0].advancePx,24+83);
});
test('contextual word space leaves Chinese and paragraph indentation alone',()=>{
 const a=measure('　Side 3　中文','main_scroll').rows[0].glyphs;
 assert.deepEqual(a.filter(g=>/[ 　]/.test(g.text)).map(g=>g.advance),[24,8,24]);
 assert.equal(measure('Ｓｉｄｅ　３','main_scroll').rows[0].advancePx,83);
 assert.equal(measure('Side  3','main_scroll').rows[0].glyphs[4].advance,24);
});
test('centering shares advance and native odd-width truncation',()=>{
 const r=center('Side 3','main_scroll',100).rows[0];
 assert.equal(r.originX,59);assert.equal(r.glyphs[0].x,56);
 assert.equal(r.advancePx,measure('Side 3','main_scroll').rows[0].advancePx);
});
test('migration emits neither scopes nor per-character dimensions',()=>{
 const text='前往<z>Side 3</z>，确认敌人所在的位置，然后开始作战。';
 const r=layout(text,'story');
 assert.ok(!/[<>]/.test(r.text));assert.equal(r.compiledText,r.text);
 assert.equal(r.text.replaceAll('\n　',''),migrateCompact(text,'story'));
 assert.ok(r.rows.every(row=>row.occupiedPx<=r.widthPx));
 assert.equal(layout(r.text,'story').text,r.text);
 assert.throws(()=>migrateCompact('<z>Side 3','story'));
});
test('tag-free wrapping protects Side 3 and preserves controls',()=>{
 const input='国'.repeat(20)+'Side 3，<color:03>继续前进！';
 const r=layout(input,'story');
 assert.ok(r.text.includes('Side 3'));assert.ok(r.text.includes('<color:03>'));
 assert.ok(r.rows.length>1);assert.ok(r.rows.every(row=>row.occupiedPx<=r.widthPx));
 assert.equal(r.text.replaceAll('\n　',''),input);
});
test('candidate selection does not silently change production measurement',()=>{
 assert.equal(legacyMeasure('Side 3','main_scroll').rows[0].advancePx,144);
 assert.equal(measure('Side 3','main_scroll').rows[0].advancePx,83);
});
test('tag-free reflow matches actual corpus dialogue replay in ARMSX2',()=>{
 const proof=JSON.parse(readFileSync(new URL('./fixtures/proportional-dialogue.json',import.meta.url)));
 for(const c of proof.cases){
  const r=layout(c.source,'story');
  assert.equal(r.text,c.text,c.id);assert.equal(r.fontSha256,c.fontSha256);
  assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-240,61+i*14,g.width,g.height])),c.geometry,c.id);
 }
});
test('identifier punctuation matches native EE measured widths and preserves standalone punctuation',()=>{
 for(const [text,width] of [['Mk-II',59],['12.5',54],['A/B',50],['-',24]])
  assert.equal(measure(text,'main_scroll').rows[0].advancePx,width,text);
 assert.equal(measure('甲-乙','main_scroll').rows[0].advancePx,72);
 assert.equal(measure('A<color:03> B','main_scroll').rows[0].glyphs[1].advance,24);
 assert.equal(measure('A <color:03>B','main_scroll').rows[0].glyphs[1].advance,24);
});
test('weapon measurement reproduces real-name ARMSX2 list geometry',()=>{
 const c=JSON.parse(readFileSync(new URL('./fixtures/proportional-weapon.json',import.meta.url)));
 const r=measure(c.text,'weapon');assert.equal(r.fontSha256,c.fontSha256);
 assert.deepEqual(r.rows[0].glyphs.map(g=>[g.x-159,-52,g.width,g.height]),c.geometry);
 assert.equal(r.rows[0].advancePx,c.advance);
});
test('control parameters cannot be mistaken for visible source digits',()=>{
 assert.equal(measure('<color:03>3.5','weapon').rows[0].advancePx,measure('3.5','weapon').rows[0].advancePx);
 assert.equal(measure('<color:03>3 <color:05>5','weapon').rows[0].glyphs[1].advance,16);
});
test('shared constrained solver preserves timing rows without z tags',()=>{
 const r=layout('“目标<z>Side 3</z>已锁定！\n　立即攻击！”','battle',{preserveLineCount:true});
 assert.equal(r.rows.length,2);assert.ok(!r.compiledText.includes('<z>'));
 assert.ok(r.rows.every(row=>row.occupiedPx<=r.widthPx));
 assert.throws(()=>layout('国'.repeat(50),'story',{maxLines:1}));
});
test('fixed native fields retain encoder byte capacities and exact field count',async()=>{
 const {layoutFixedFields}=await import('./proportional.mjs');
 const fields=[{text:'　<z>Side 3</z>'+'国'.repeat(12),capacityBytes:41,terminatorBytes:1},{text:'国'.repeat(20),capacityBytes:41,terminatorBytes:1}];
 const encodedCharacterBytes=Object.fromEntries(Array.from('　Side 3国').map(ch=>[ch,2]));
 const r=layoutFixedFields(fields,'main_scroll',{encodedCharacterBytes});
 assert.equal(r.fields.length,2);assert.equal(r.rows.length,2);
 assert.equal(r.fields.map(f=>f.text).join(''),'　Side 3'+'国'.repeat(32));
 assert.ok(r.fields.every(f=>f.encodedBytes<=f.capacityBytes));
 assert.ok(r.rows.every(row=>row.occupiedPx<=528));
 assert.ok(r.fields.some(f=>f.encodedBytes===41));
 assert.throws(()=>layoutFixedFields(fields.map(f=>({...f,capacityBytes:20})),'main_scroll',{encodedCharacterBytes}),e=>e.code==='field_capacity');
});
test('candidate resource overrides and prose paragraph ownership survive integration',()=>{
 const r=layout('　Side 3'+'国'.repeat(25)+'\n\n　'+'国'.repeat(10),'main_scroll',{resourceId:'summary/03/000'});
 assert.equal(r.widthPx,504);assert.ok(r.rows.some((row,i)=>!row.text.trim()&&r.rows[i+1]?.text.startsWith('　')));
 assert.ok(r.rows.every(row=>row.occupiedPx<=504));
});
test('a trailing fullwidth space may shrink when the next word joins the row',()=>{
 const source='国'.repeat(22)+'I I';
 assert.ok(measure(source,'story').rows[0].occupiedPx<=483);
 const r=layout(source,'story');assert.equal(r.rows.length,1);assert.equal(r.text,source);
});
test('centering agrees with natural menu consumers in ARMSX2',()=>{
 const proof=JSON.parse(readFileSync(new URL('./fixtures/proportional-alignment.json',import.meta.url)));
 for(const c of proof.cases){
  const r=center(c.text,'weapon',c.center).rows[0];
  assert.equal(c.candidateMeasure,c.measureReturnsFullWidth?r.advancePx:-Math.trunc(r.advancePx/2));
  assert.deepEqual(r.glyphs.map(g=>[g.x,c.geometry[0][1],g.width,g.height]),c.geometry);
 }
});
test('keyword segments match real EE geometry including consecutive and mixed terms',()=>{
 const cases=JSON.parse(readFileSync(new URL('./fixtures/proportional-keywords.json',import.meta.url)));
 for(const c of cases){
  const r=layout(c.source,'story',{keywordLinks:true});
  assert.equal(r.compiledText,c.text,c.id);
  assert.equal(r.fontSha256,c.fontSha256,c.id);
  assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-240,61+14*i,g.width,g.height])),c.geometry,c.id);
 }
});
test('historical SP synopsis rows retain recorded ARMSX2 glyph geometry',()=>{
 const cases=JSON.parse(readFileSync(new URL('./fixtures/proportional-flow.json',import.meta.url)));
 for(const c of cases){
  const r=measure(c.text,'sp_flow');
  assert.equal(r.text,c.text);assert.equal(r.fontSha256,c.fontSha256);
  assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-224,-48+i*12,g.width,g.height])),c.geometry);
 }
});
test('historical vertical scroll rows retain recorded ARMSX2 glyph geometry',()=>{
 const c=JSON.parse(readFileSync(new URL('./fixtures/proportional-scroll.json',import.meta.url)));
 const r=measure(c.text,'main_scroll',{resourceId:c.resourceId});
 assert.equal(r.text,c.text);assert.equal(r.fontSha256,c.fontSha256);
 assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-252,c.originY+i*12,g.width,g.height])),c.geometry);
 assert.deepEqual(r.text.split('\n').filter(x=>!x.trim()),['　','　']);
});
test('Chinese punctuation reduces advance without scaling existing glyph cells',()=>{
 const text='“高达Mk-II，出击！目标是Side 3。”';
 const native=measure(text,'story').rows[0];const compact=measure(text,'story',{chinesePunctuation:'compact'}).rows[0];
 assert.equal(native.advancePx,344);assert.equal(compact.advancePx,319);
 for(let i=0;i<native.glyphs.length;i++){
  assert.equal(compact.glyphs[i].width,native.glyphs[i].width);
  assert.equal(compact.glyphs[i].height,native.glyphs[i].height);
 }
 assert.ok(compact.glyphs.filter(g=>'“”，！。'.includes(g.text)).every(g=>g.advance===16));
});
test('Chinese punctuation preserves pairs, authored controls and line-break rules',()=>{
 const options={chinesePunctuation:'compact'};
 assert.equal(measure('……——','story',options).rows[0].advancePx,84);
 assert.equal(measure('<width:09><space:09>，','story',options).rows[0].advancePx,9);
 const text='“'+'国'.repeat(22)+'，高达Mk-II……继续——出击！”';
 const r=layout(text,'story',options);
 assert.ok(r.rows.every(row=>!/^\s*[，。、！？：；”’）》】]/u.test(row.text)));
 assert.ok(r.rows.every(row=>!/[“‘（《【]$/u.test(row.text)));
 assert.ok(!r.text.includes('…\n…'));assert.ok(!r.text.includes('—\n—'));
 assert.equal(r.text.replaceAll('\n','').replaceAll('　',''),text);
});
test('Latin baseline offset preserves descenders and leaves horizontal metrics unchanged',()=>{
 const r=measure('目标是Side 3，Hgpxyq。','story',{chinesePunctuation:'compact'}).rows[0];
 for(const g of r.glyphs){
  assert.equal(g.yOffset,/[A-Za-z0-9]/.test(g.text)?-1:0);
 }
 assert.equal(measure('Side 3','story').rows[0].advancePx,measure('Side 3','story',{chinesePunctuation:'compact'}).rows[0].advancePx);
 const letters=r.glyphs.filter(g=>/[Hgpxyq]/.test(g.text));
 assert.ok(letters.every(g=>g.height===13&&g.yOffset===-1));
});
test('letter and numeral baselines match actual ARMSX2 submitted Y coordinates',()=>{
 const cases=JSON.parse(readFileSync(new URL('./fixtures/proportional-numeric-baseline.json',import.meta.url)));
 for(const c of cases){
  // Historical schema5 capture precedes slash-spacing integration and the
  // opener-width continuation indent (rows then began with a full-width 0x8140).
  const r=measure(c.text,'story',{chinesePunctuation:'compact',spacedSlash:false,continuationIndent:'fullwidth'});
  assert.equal(r.fontSha256,c.fontSha256);
  assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-240,61+i*14+(g.yOffset??0),g.width,g.height])),c.geometry);
 }
});

test('proportional prose keeps panel fill ahead of perfect narrow alignment',()=>{
 const cases=[
  ['library_robot','从第1话《愤怒吧！木卫一的战士》开始登场的宇宙恐龙第1号。用各种破坏光线和制造漩涡的能力对三位一体城发动了攻击。'],
  ...['main_flow','sp_flow','main_scroll','sp_scroll','library_character','library_glossary'].map(scene=>[scene,'中文测试文本'.repeat(19)+'，前往Side 3，目标CIWS/RX-78，确认。']),
 ];
 for(const [scene,text] of cases){
  const options={chinesePunctuation:'compact'};
  const r=layout(text,scene,options);
  assert.ok(r.selectedWidthPx>=r.widthPx-r.step,scene);
  assert.ok(r.rows.every(row=>row.occupiedPx<=r.widthPx),scene);
  assert.equal(r.text.replaceAll('\n',''),text,scene);
  assert.equal(layout(r.text,scene,options).text,r.text,scene);
  if(text.includes('Side 3'))assert.ok(r.text.includes('Side 3')&&r.text.includes('CIWS/RX-78'),scene);
 }
});
test('overwide Latin identifiers can split without recursive tokenization',()=>{
 const r=layout('A'.repeat(100),'main_flow');
 assert.equal(r.text.replaceAll('\n',''),'A'.repeat(100));
 assert.ok(r.rows.every(row=>row.occupiedPx<=r.widthPx));
});


test('main combat and SP weapon lists retain distinct native geometry',()=>{
 const main=measure('中CIWS / RX-78文','weapon_main',{chinesePunctuation:'compact'}).rows[0];
 const sp=measure('中CIWS / RX-78文','weapon',{chinesePunctuation:'compact'}).rows[0];
 assert.equal(main.glyphs[0].width,20);assert.equal(main.glyphs[0].advance,20);
 assert.equal(sp.glyphs[0].width,16);assert.equal(sp.glyphs[0].advance,16);
 assert.equal(main.glyphs[1].width,14);assert.equal(sp.glyphs[1].width,12);
 assert.equal(main.glyphs[0].height,9);assert.equal(sp.glyphs[0].height,9);
 assert.equal(measure('<z>CIWS/RX-78</z>','weapon_main').rows[0].advancePx,
              measure('CIWS/RX-78','weapon_main').rows[0].advancePx);
});
