import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {layout,measure,validate,expandCompact,dispatch,getScene,sceneIds} from './engine.mjs';
import {respond} from './cli-handler.mjs';

test('verified LRPS2 mixed sample: line breaks and native geometry',()=>{
 const proof=JSON.parse(readFileSync(new URL('../../docs/issue-assets/mixed-compact-20261028/evidence.json',import.meta.url)));
 for(const scene of proof.cases){
  for(const sample of scene.cases){
   const rows=measure(sample.authored,scene.scene).rows;
   assert.deepEqual(rows.map(r=>r.advancePx),sample.row_advances,sample.id);
   for(const [i,row]of rows.entries())assert.deepEqual(row.glyphs.map(g=>[g.text,g.x,g.width,g.height]),sample.rows[i].glyphs.map(g=>[g.ch,g.x,g.w,g.h]));
   const native=proof.results.find(r=>r.scene===scene.scene).cases.find(r=>r.id===sample.id);
   const expected=scene.scene==='story'?rows.at(-1).glyphs:rows.flatMap(r=>r.glyphs);
   assert.equal(expected.length,native.verified_glyphs);
   const selectedRows=scene.scene==='story'?[rows.at(-1)]:rows;
   const originX=scene.scene==='story'?-240:-160, originY=scene.scene==='story'?61+(rows.length-1)*14:84;
   const nativeExpected=selectedRows.flatMap((row,j)=>row.glyphs.map(g=>[originX+g.x,originY+j*scene.line_step,g.width,g.height]));
   assert.deepEqual(nativeExpected,native.geometry.records,scene.scene+':'+sample.id);
  }
  const sample=scene.cases.find(c=>c.id==='compact-filled');
  assert.equal(layout(sample.source,scene.scene,{preserveLineCount:false}).text,sample.authored);
 }
});
test('quote, indent, overhang and scene restoration all occupy physical width',()=>{
 assert.equal(validate('“'+'国'.repeat(20)+'”','battle').valid,false);
 assert.deepEqual(measure('“'+'国'.repeat(20)+'\n　'+'国'.repeat(19)+'”','battle').rows.map(r=>r.occupiedPx),[462,462]);
 assert.equal(measure('国'.repeat(15)+'<z>ABCDEFGHIJK</z>','battle').rows[0].occupiedPx,464);
 for(const scene of ['story','battle'])for(const run of ['MS-013','Gundam01','013','80%']){
  const s=getScene(scene),r=measure(`甲<z>${run}</z>乙`,scene);assert.equal(r.rows[0].advancePx,2*s.step+run.length*12);assert.deepEqual(r.state,{width:s.width,height:s.height,step:s.step});
 }
});
test('keep words, controls, identifier and paired punctuation intact',()=>{
 const text='“目标<z>RX-78</z>和$n，<color:03>立即开始战斗，确认敌人的位置！”';
 const r=layout(text,'story');assert.equal(r.text.replace(/\n　/g,''),text);assert.ok(r.text.includes('战斗'));assert.ok(r.text.includes('<z>RX-78</z>'));assert.ok(r.rows.flatMap(r=>r.glyphs).some(g=>g.placeholder));
 assert.equal(layout(r.text,'story').text,r.text);
});
test('battle keeps existing timing row count unless explicitly allowed',()=>{
 assert.throws(()=>layout('“'+'国'.repeat(30)+'”','battle'),/cannot fit/);
 const r=layout('“'+'国'.repeat(30)+'”','battle',{preserveLineCount:false});assert.equal(r.rows.length,2);
 assert.equal(layout(r.text.replace(/\n/g,'\\n'),'battle',{escapedNewlines:true}).text,r.text.replace(/\n/g,'\\n'));
});
test('all prose scenes retain paragraphs, hard blank rows and use their own steps',()=>{
 for(const id of ['main_flow','sp_flow','main_scroll','sp_scroll']){
  const text='　'+'国'.repeat(30)+'。\n　\n　第二段<z>013</z>开始。';
  const r=layout(text,id);assert.equal(r.text.replace(/[\n　]/g,''),text.replace(/[\n　]/g,''));assert.ok(r.text.includes('\n　\n　第二段'));assert.ok(r.rows.every(row=>row.occupiedPx<=getScene(id).widthPx));
  assert.equal(layout(r.text,id).text,r.text);
 }
 assert.equal(expandCompact('<z>013</z>','sp_flow'),'<width:0C><space:0B><height:09>013<width:10><space:10><height:8A>');
});
test('state crosses physical rows, and percent restoration is not a format token',()=>{
 assert.deepEqual(measure('<space:0C>甲\n乙','battle').rows.map(r=>r.advancePx),[12,12]);
 assert.equal(measure('<z>80%</z>甲','battle').rows[0].advancePx,58);
 assert.ok(expandCompact('<z>80%</z>','battle').includes('%<space:16><width:16>'));
});
test('native keyword delimiters are invisible only with the explicit keyword owner',()=>{
 assert.equal(measure('《Side 3》','story',{keywordLinks:true}).rows[0].advancePx,126);
 assert.equal(measure('《Side 3》','story').rows[0].advancePx,168);
 assert.throws(()=>measure('《甲《乙》','story',{keywordLinks:true}),/Nested/);
});
test('unsupported and malformed owners fail closed rather than inventing widths',()=>{
 for(const text of ['<tm>甲</tm>','＜ｔｍ＞甲＜／ｔｍ＞','@3国','[12]甲','<width:00>甲','<height:0A>甲','<unknown:12>甲','<z>甲</z>','<z><z>A</z></z>'])assert.throws(()=>layout(text,'story'),{name:'LayoutError'},text);
 assert.throws(()=>layout('甲','missing'),/Unknown scene/);
 assert.throws(()=>layout('　对齐卡片','story'),/owner-specific/);
 assert.equal(respond({scene:'story',text:'甲'}).ok,true);assert.equal(respond({scene:'unknown',text:'甲'}).error.code,'unknown_scene');
});
test('browser-safe module and backend dispatch are the same API, no caller state leaks',()=>{
 for(const scene of sceneIds){const input={scene,text:'甲<z>MS013</z>乙',action:'layout',options:{preserveLineCount:false}};assert.deepEqual(dispatch(input),respond(input).result);}
 const s=getScene('battle');s.widthPx=1;s.compact.restore_space=1;s.protectedTerms.length=0;assert.equal(getScene('battle').widthPx,462);assert.equal(getScene('battle').compact.restore_space,22);
 const source=readFileSync(new URL('./engine.mjs',import.meta.url),'utf8');assert.doesNotMatch(source,/from ['"]node:|\bprocess\.|\bdocument\.|\bwindow\./);
});
test('scene and resource limits cannot be overridden by malformed caller options',()=>{
 for(const scene of ['constructor','__proto__'])assert.throws(()=>getScene(scene),/Unknown scene/);
 for(const options of [{maxLines:3},{maxLines:0},{maxLines:1.5},{placeholderCells:-1},{placeholderCells:Infinity},{preserveLineCount:'false'},{protectedTerms:['x\ny']},{initialState:{width:1,height:1,step:1}}])assert.throws(()=>layout('甲','battle',options),{name:'LayoutError'});
 assert.throws(()=>layout('甲','story',null),{name:'LayoutError'});
});

test('protected names can contain a whole compact scope without truncating identifiers',()=>{
 const text='“'+'国'.repeat(17)+'<z>013</z>特别小队发动攻击！”';
 const r=layout(text,'story',{protectedTerms:['013特别小队']});
 assert.ok(r.text.includes('\n　<z>013</z>特别小队'));assert.equal(r.text.replace(/\n　/g,''),text);
});
test('reviewed native prose widths replace the older narrow author budgets',()=>{
 assert.equal(getScene('main_flow').widthPx,480);assert.equal(getScene('sp_flow').widthPx,480);
 assert.equal(getScene('main_scroll').widthPx,528);assert.equal(getScene('sp_scroll').widthPx,575);
 assert.equal(getScene('main_scroll_strip').widthPx,504);
 assert.equal(layout('甲','main_scroll',{resourceId:'summary/03/000'}).scene,'main_scroll_strip');
 assert.equal(layout('甲','main_scroll',{resourceId:'summary/04/000'}).widthPx,504);
});
test('flow and scroll prose fills rows without word protection',()=>{
 const text='国'.repeat(14)+'甲乙丙丁戊己庚辛壬癸'+'国'.repeat(10);
 const r=layout(text,'main_flow',{protectedTerms:['甲乙丙丁戊己庚辛壬癸']});
 assert.deepEqual(r.rows.map(row=>row.occupiedPx),[480,64]);assert.ok(r.text.includes('国'.repeat(6)+'\n'+'国'.repeat(4)));
 const closed=layout('国'.repeat(27)+'<z>MS-013</z>'+'国'.repeat(10),'main_flow');
 assert.ok(closed.text.includes('<z>MS-013</z>'));assert.ok(closed.rows.every(row=>row.occupiedPx<=480));
});
test('flow and scroll fill every nonfinal row, retaining first indent',()=>{
 for(const scene of ['main_flow','sp_flow','main_scroll','sp_scroll','main_scroll_strip']){
  const s=getScene(scene);assert.equal(s.protectWords,false);
  for(let n=1;n<=85;n++)for(const indent of ['', '　']){
   const r=layout(indent+'国'.repeat(n),scene),widths=r.rows.map(row=>row.occupiedPx);
   assert.equal(r.rows.length,Math.ceil((n+indent.length)/s.columns));
   assert.ok(widths.slice(0,-1).every(w=>w===s.widthPx));
   assert.ok(widths.at(-1)<=s.widthPx);
   assert.equal(r.text.replace(/\n/g,''),indent+'国'.repeat(n));
  }
 }
 const text='　'+'国'.repeat(53)+'\n　\n　'+'甲'.repeat(35);
 const r=layout(text,'sp_scroll');assert.ok(r.text.includes('\n　\n　'));
});

test('compact numbering does not hide independent choice ownership',()=>{
 assert.throws(()=>layout('“怎么做？”\n“<z>1</z><z>．</z>继续”\n“<z>2</z><z>．</z>返回”','story'),/owner-specific/);
 assert.equal(layout('甲\n\n乙','main_scroll_strip').text,'甲\n　\n乙');
});

test('library bodies have independent width, height and compact restoration',()=>{
 for(const [domain,columns,height,letter,digit] of [['character',16,12,12,11],['robot',26,10,11,10],['glossary',25,12,12,11]]){
  const scene='library_'+domain,s=getScene(scene);
  assert.equal(s.widthPx,columns*21);assert.equal(s.height,height);
  const text='目标<z>MS-013</z>已经进入指定区域，'+ '队员立即开始行动。'.repeat(7);
  const r=layout(text,scene);assert.ok(r.valid);assert.equal(r.text.replaceAll('\n',''),text);
  const m=measure('中<z>A1</z>文',scene).rows[0].glyphs;
  assert.deepEqual(m.map(g=>g.height),[height,letter,digit,height]);
  assert.deepEqual(m.map(g=>g.advance),[21,12,12,21]);
  assert.equal(layout(r.text,scene).text,r.text);
 }
});


test('one width search covers all paragraphs, allowing short tails and native compact overhang',()=>{
 const text='　幻痛部队的众人与新队员见面。望着他们，阿尼莫奈与辛西亚不由得看到了自己的影子。\n　与此同时，贝克与科伦在麦康奈尔基地附近的城镇相遇。原本剑拔弩张的两人，在异星人出现后转而并肩迎敌。\n　<z>013</z>特别小队也赶来支援，合力击退了异星人部队。但战斗结束后，奥尔却因<width:10><space:10>禁语受到刺激，精神失去平衡。\n　回到基地后，贝克与科伦正式加入队伍。紧接着，与补给物资一同到来的，还有奇美拉的极艾博士。';
 const r=layout(text,'sp_flow',{maxLines:11});
 assert.equal(r.widthPx,480);assert.equal(r.selectedWidthPx,479);
 assert.deepEqual(r.widthSelection.nonfinalWidthsPx,[464,464,465,464]);
 assert.equal(r.widthSelection.withinTolerance,true);
 assert.equal(r.text.replaceAll('\n',''),text.replaceAll('\n',''));
 assert.equal(layout(r.text,'sp_flow',{maxLines:11}).text,r.text);
 assert.equal(r.text.split('\n').filter(s=>s.startsWith('　')).length,4);
});
test('uniform width search leaves already aligned nonfinal rows at the maximum width',()=>{
 const r=layout('　'+'国'.repeat(63)+'\n　'+'甲'.repeat(35),'main_flow',{maxLines:8});
 assert.equal(r.selectedWidthPx,480);assert.equal(r.widthSelection.testedWidths,1);
 assert.deepEqual(r.widthSelection.nonfinalWidthsPx,[480,480,480]);
 assert.equal(layout('甲'.repeat(40),'story').widthSelection,undefined);
});


test('width trials respect owner row budgets and keep punctuation pairs atomic',()=>{
 const text='　'+'甲'.repeat(29)+'。'+'乙'.repeat(33)+'\n　'+'丙'.repeat(42)+'。';
 const baselineRows=layout(text,'main_flow',{packing:'balanced_width'}).rows.length;
 for(const budget of [undefined,6]){
  const options=budget?{maxLines:budget}:{};
  const result=layout(text,'main_flow',options);
  assert.ok(result.rows.every(row=>row.occupiedPx<=480));
  assert.ok(result.rows.length<=(budget??baselineRows));
  assert.equal(result.text.replaceAll('\n',''),text.replaceAll('\n',''));
 }
 assert.equal(layout('　'+'甲'.repeat(18)+'……'+'乙'.repeat(45),'sp_flow',{maxLines:5}).text.replaceAll('\n',''),'　'+'甲'.repeat(18)+'……'+'乙'.repeat(45));
});
