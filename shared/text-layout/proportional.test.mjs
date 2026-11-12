import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {measure,center,layout,migrateCompact} from './proportional.mjs';
import {measure as legacyMeasure, validate, getScene} from './engine.mjs';
import {proportionalMetrics} from './proportional-metrics.mjs';

test('SP map dialogue uses pixel widths and reserves four pixels for final punctuation',()=>{
 const scene='sp_story_map', options={typography:'proportional',chinesePunctuation:'compact'};
 const mixed='“4分钟内击坠100架敌机，作战即告成功。”';
 assert.equal(layout(mixed,scene).text,mixed);
 assert.equal(measure('中'.repeat(21),scene).rows[0].occupiedPx,420);
 const hanging='中'.repeat(19)+'20。';
 const measured=validate(hanging,scene,options);
 assert.equal(measured.rows[0].occupiedPx,422);
 assert.equal(measured.rows[0].fitPx,418);
 assert.equal(measured.valid,true);
 assert.equal(layout(hanging,scene).text,hanging);
 assert.equal(validate(hanging+'中',scene,options).valid,false);
 assert.equal(validate('中'.repeat(20)+'20',scene,options).valid,false);
 assert.equal(validate('中'.repeat(20)+'2。',scene,options).valid,false);
});

test('SP map wrapping adds breaks only inside the overflowing authored row',()=>{
 const scene='sp_story_map', short='　原有断行。';
 const manual='　第一句。\n'+short;
 assert.equal(layout(manual,scene).text,manual);
 const long='“'+ '中'.repeat(23);
 const input=long+'\n'+short+'”';
 const fitted=layout(input,scene).text;
 assert.equal(fitted.split('\n').length,3);
 assert.ok(fitted.endsWith('\n'+short+'”'));
 assert.equal(fitted.replace('\n　',''),input);
 assert.equal(layout(fitted,scene).text,fitted);
 assert.throws(()=>layout(input+'\n尾句。',scene),{code:'overflow'});
});

test('SP map numeric templates reserve one unbreakable runtime slot',()=>{
 const scene='sp_story_map';
 for(const template of ['＜ｔｍ＞获得资金＜／ｔｍ＞','＜tm＞获得资金＜／tm＞','<tm>获得资金</tm>']){
  const authored='“获得资金'+template+'！\n　目标达成！”';
  const checked=layout(authored,scene);
  assert.equal(checked.text,authored);
  assert.equal(checked.rows[0].glyphs.find(g=>g.placeholder).width,160);
  const long='“'+'中'.repeat(17)+template+'！目标达成！”';
  const wrapped=layout(long,scene);
  assert.ok(wrapped.rows.length>1);
  assert.ok(wrapped.rows.some(row=>row.text.includes(template)));
  assert.throws(()=>layout(authored.replace(template,template.replace('资金','\n　资金')),scene),{code:'owner_contract'});
 }
});

test('scroll measurement reproduces the 2026-11-12 ARMSX2 capture with the HarmonyOS bank',()=>{
 // Replaces the Side 3 capture taken with the stock full-width Latin glyphs.
 const proof=JSON.parse(readFileSync(new URL('./fixtures/proportional-scroll-runtime-20261112.json',import.meta.url)));
 const measured=measure(proof.text,'main_scroll',{chinesePunctuation:'compact'});
 assert.equal(measured.rows.length,proof.rows.length);
 const order=(a,b)=>a[0]-b[0]||a[1]-b[1];
 measured.rows.forEach((row,i)=>{
  const left=proof.rows[i][0][0]-row.glyphs[0].x;
  assert.deepEqual(row.glyphs.map(g=>[g.x+left,g.width,g.height]).sort(order),proof.rows[i].map(([x,,w,h])=>[x,w,h]).sort(order),`row ${i+1}`);
 });
 assert.equal(measure('　Side 3','main_scroll').rows[0].advancePx,24+57);
});
test('contextual word space leaves Chinese and paragraph indentation alone',()=>{
 const a=measure('　Side 3　中文','main_scroll').rows[0].glyphs;
 assert.deepEqual(a.filter(g=>/[ 　]/.test(g.text)).map(g=>g.advance),[24,5,24]);
 assert.equal(measure('Ｓｉｄｅ　３','main_scroll').rows[0].advancePx,57);
 assert.equal(measure('Side  3','main_scroll').rows[0].glyphs[4].advance,24);
});
test('centering shares advance and native odd-width truncation',()=>{
 const r=center('Side 3','main_scroll',100).rows[0];
 assert.equal(r.originX,72);assert.equal(r.glyphs[0].x,72-proportionalMetrics.profiles.main_scroll.glyphs.S.bearing);
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
 assert.equal(measure('Side 3','main_scroll').rows[0].advancePx,57);
});
test('tag-free reflow matches actual corpus dialogue replay in ARMSX2',()=>{
 const proof=JSON.parse(readFileSync(new URL('./fixtures/proportional-dialogue.json',import.meta.url)));
 for(const c of proof.cases){
  const r=layout(c.source,'story');
  // The line breaks still hold; the glyph geometry recorded here used the stock Latin
  // glyphs and is superseded by the HarmonyOS-bank recapture checked below.
  assert.equal(r.text,c.text,c.id);assert.equal(r.fontSha256,c.fontSha256);
 }
});
test('identifier punctuation matches native EE measured widths and preserves standalone punctuation',()=>{
 for(const [text,width] of [['Mk-II',48],['12.5',44],['A/B',35],['-',24]])
  assert.equal(measure(text,'main_scroll').rows[0].advancePx,width,text);
 assert.equal(measure('甲-乙','main_scroll').rows[0].advancePx,72);
 assert.equal(measure('A<color:03> B','main_scroll').rows[0].glyphs[1].advance,24);
 assert.equal(measure('A <color:03>B','main_scroll').rows[0].glyphs[1].advance,24);
});
test('weapon measurement reproduces the 2026-11-12 SP Battle Viewer list capture',()=>{
 // "12.5毫米CIWS" replayed into the SP weapon list on the HarmonyOS-bank candidate.
 const c=JSON.parse(readFileSync(new URL('./fixtures/proportional-weapon.json',import.meta.url)));
 const r=measure(c.text,'weapon',{chinesePunctuation:'compact'});assert.equal(r.fontSha256,c.fontSha256);
 assert.deepEqual(r.rows[0].glyphs.map(g=>[g.x-159,-52,g.width,g.height]),c.geometry);
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
test('centering agrees with the name the SP Battle Viewer centres itself',()=>{
 // Natural draw, no replay: the game measures "巴尔戈拉（1号机）" and centres it on x=170.
 const c=JSON.parse(readFileSync(new URL('./fixtures/proportional-centering-runtime-20261112.json',import.meta.url)));
 const r=center(c.text,'weapon',170,{chinesePunctuation:'compact'}).rows[0];
 assert.equal(r.originX,170-Math.trunc(r.advancePx/2));
 assert.deepEqual(r.glyphs.map(g=>[g.x,-15,g.width,g.height]),c.geometry);
});
test('keyword segments match real EE geometry including consecutive and mixed terms',()=>{
 // Packed dialogue replayed on the HarmonyOS-bank candidate (2026-11-12). The packed bytes
 // predate the opener-width continuation indent, so rows 2+ begin with a full-width space.
 const cases=JSON.parse(readFileSync(new URL('./fixtures/proportional-keywords.json',import.meta.url)));
 assert.equal(cases.length,4);
 for(const c of cases){
  assert.equal(layout(c.source,'story',{keywordLinks:true}).compiledText,c.text,c.id);
  const r=measure(c.text,'story',{keywordLinks:true,chinesePunctuation:'compact',continuationIndent:'fullwidth'});
  assert.equal(r.fontSha256,c.fontSha256,c.id);
  assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-240,61+14*i,g.width,g.height])),c.geometry,c.id);
 }
});
test('SP synopsis rows match the 2026-11-12 ARMSX2 capture',()=>{
 // Natural synopsis page of the SP candidate with the HarmonyOS bank: eight visible rows.
 const c=JSON.parse(readFileSync(new URL('./fixtures/proportional-flow-runtime-20261112.json',import.meta.url)));
 const r=measure(c.text,'sp_flow',{chinesePunctuation:'compact'});
 assert.equal(r.rows.length,8);
 assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-224,c.originY+i*c.rowStep,g.width,g.height])),c.geometry);
});
test('vertical scroll rows match the 2026-11-12 ARMSX2 capture of the same text',()=>{
 // The stored rows replayed into the opening scroll of the HarmonyOS-bank candidate;
 // the screen shows the first 13 of the 16 rows.
 const c=JSON.parse(readFileSync(new URL('./fixtures/proportional-scroll.json',import.meta.url)));
 const r=measure(c.text,'main_scroll',{resourceId:c.resourceId,chinesePunctuation:'compact'});
 assert.equal(r.text,c.text);assert.equal(r.fontSha256,c.fontSha256);
 const geometry=r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-252,c.originY+i*12,g.width,g.height]));
 assert.equal(c.evidence.rowsCaptured,13);
 assert.deepEqual(geometry.slice(0,c.geometry.length),c.geometry);
 assert.deepEqual(r.text.split('\n').filter(x=>!x.trim()),['　','　']);
});
test('Chinese punctuation reduces advance without scaling existing glyph cells',()=>{
 const text='“高达Mk-II，出击！目标是Side 3。”';
 const native=measure(text,'story').rows[0];const compact=measure(text,'story',{chinesePunctuation:'compact'}).rows[0];
 assert.equal(native.advancePx,343);assert.equal(compact.advancePx,318);
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
test('story letters sit on the hanzi baseline at hanzi height and keep horizontal metrics',()=>{
 const r=measure('目标是Side 3，Hgpxyq。','story',{chinesePunctuation:'compact'}).rows[0];
 for(const g of r.glyphs){
  assert.equal(g.yOffset,0);
 }
 assert.equal(measure('Side 3','story').rows[0].advancePx,measure('Side 3','story',{chinesePunctuation:'compact'}).rows[0].advancePx);
 const letters=r.glyphs.filter(g=>/[Hgpxyq]/.test(g.text));
 assert.ok(letters.every(g=>g.height===12&&g.yOffset===0));
});
test('ADV glyph geometry matches the 2026-11-12 ARMSX2 recapture exactly',()=>{
 // Dialogue lines, numerals, mixed identifiers and 0/O pairs, recorded on the candidate
 // with the HarmonyOS bank: every glyph, Latin included, is submitted in the 21x12 cell.
 const proof=JSON.parse(readFileSync(new URL('./fixtures/proportional-adv-runtime-20261112.json',import.meta.url)));
 assert.ok(proof.cases.length>=5);
 for(const c of proof.cases){
  const r=measure(c.text,'story',{chinesePunctuation:'compact'});
  assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x-240,61+i*14+(g.yOffset??0),g.width,g.height])),c.geometry,c.id);
 }
});

test('battle subtitle and tactical-map glyph geometry match the 2026-11-12 ARMSX2 captures',()=>{
 // Promoted current ISOs with the HarmonyOS bank: SP battle line buffer (22x11 cell, rows from x=-160)
 // and the Original stage 013 map box (20x11 cell). Body rows only, in drawing order.
 for(const [name,scene] of [['battle','battle'],['map','story_map']]){
  const proof=JSON.parse(readFileSync(new URL(`./fixtures/proportional-${name}-runtime-20261112.json`,import.meta.url)));
  assert.ok(proof.cases.length>=2,name);
  for(const c of proof.cases){
   const r=measure(c.text,scene,{chinesePunctuation:'compact'});
   const left=c.geometry[0][0]-r.rows[0].glyphs[0].x,top=c.geometry[0][1];
   assert.deepEqual(r.rows.flatMap((row,i)=>row.glyphs.map(g=>[g.x+left,top+i*getScene(scene).lineStep+(g.yOffset??0),g.width,g.height])),c.geometry,c.id);
  }
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
 // Bank Latin is drawn in the scene's own hanzi cell.
 assert.equal(main.glyphs[1].width,20);assert.equal(sp.glyphs[1].width,16);
 assert.equal(main.glyphs[0].height,9);assert.equal(sp.glyphs[0].height,9);
 assert.equal(measure('<z>CIWS/RX-78</z>','weapon_main').rows[0].advancePx,
              measure('CIWS/RX-78','weapon_main').rows[0].advancePx);
});
test('every scene draws bank Latin in its own hanzi cell, without lift or residual',()=>{
 const native={story:[21,12],sp_story_map:[20,11],battle:[22,11],main_flow:[16,10],sp_flow:[16,10],main_scroll:[24,12],main_scroll_strip:[24,12],sp_scroll:[25,12],weapon:[16,9],weapon_main:[20,9],library_character:[21,12],keyword_list:[18,12],library_robot:[21,10],library_glossary:[21,12]};
 assert.deepEqual(Object.keys(proportionalMetrics.profiles).sort(),Object.keys(native).sort());
 for(const [scene,[w,h]] of Object.entries(native)){
  const p=proportionalMetrics.profiles[scene];
  for(const m of [...Object.values(p.glyphs),...Object.values(p.punctuation)])
   assert.deepEqual([m.width,m.height,m.yOffset,m.baselineResidual16,m.advanceBox],[w,h,0,0,true],scene);
 }
 // Scenes of one width class share the horizontal metrics (three runtime tables).
 const horizontal=s=>JSON.stringify(Object.values(proportionalMetrics.profiles[s].glyphs).map(m=>[m.bearing,m.advance]));
 for(const group of [['story','sp_story_map','battle','weapon_main','library_character','library_robot','library_glossary'],['main_flow','sp_flow','weapon','keyword_list'],['main_scroll','main_scroll_strip','sp_scroll']])
  for(const scene of group)assert.equal(horizontal(scene),horizontal(group[0]),scene);
});
