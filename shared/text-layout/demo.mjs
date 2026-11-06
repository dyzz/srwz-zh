import {sceneIds,getScene,dispatch} from './engine.mjs';
const atlas=await fetch('./assets/native-glyphs.json').then(r=>r.json());
const atlasImage=new Image();atlasImage.src='./assets/'+atlas.image;await atlasImage.decode();
const $=id=>document.getElementById(id), select=$('scene');
const names={story:'剧情对白',battle:'战斗台词',main_flow:'本篇梗概',sp_flow:'SP梗概',main_scroll:'本篇滚动字幕',sp_scroll:'SP滚动字幕',main_scroll_strip:'本篇窄条字幕（504px）',library_character:'角色图鉴正文',library_robot:'机体图鉴正文',library_glossary:'术语图鉴正文'};
for(const id of sceneIds){const option=document.createElement('option');option.value=id;option.textContent=names[id];select.append(option);}
const samples={story:'“锁定<z>MS-013</z>后立即攻击敌方指挥机，完成任务后返回基地！”',battle:'“剩下的交给我！……随口吹的啦。我该不会染\n　上爱耍帅的毛病吧？”',prose:'　目标<z>MS-013</z>已经进入指定区域，队员们准备开始行动。请立即确认敌方的位置，然后按计划完成任务。\n　完成任务以后，所有队员返回基地。'};
function request(){return {action:'layout',scene:select.value,text:$('text').value,options:{preserveLineCount:$('preserve').checked,escapedNewlines:$('escaped').checked,protectWords:$('words').checked}};}
function updateContract(){const s=getScene(select.value);$('contract').textContent=`中文step ${s.step}px · 总行宽${s.widthPx}px · ${s.maxLines?`最多${s.maxLines}行`:'保留段落及空白行；生产字段行数由调用方传入'} · ${s.kind==='dialogue'?'续行缩进一格':'段首缩进保留，续行不额外缩进'} · 紧缩step ${s.compact.space}px · ${s.kind==='prose'?'不保词，最少行数内按像素均衡':'对白规则保持不变'}`;$('preserve').checked=s.id==='battle';$('preserve').disabled=s.kind!=='dialogue';$('words').checked=s.protectWords;$('ruler').disabled=s.kind!=='prose';}
function run(){
 $('error').textContent='';$('parity').textContent='已在浏览器本地计算；当前输入尚未与后端比较。';
 try{const result=dispatch(request());$('output').textContent=result.text;$('json').textContent=JSON.stringify(result,null,2);$('rows').replaceChildren();
  for(const [i,row]of result.rows.entries()){const tr=document.createElement('tr');for(const text of [i+1,row.advancePx+'px',row.occupiedPx+'px',result.widthPx+'px']){const td=document.createElement('td');td.textContent=text;tr.append(td);}$('rows').append(tr);}
  const sceneMetrics=getScene(result.scene),pitch=sceneMetrics.lineStep*2;
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('width',String(result.widthPx+36));svg.setAttribute('height',String(24+result.rows.length*pitch));
  result.rows.forEach((row,i)=>{const guide=document.createElementNS(ns,'rect');guide.setAttribute('x','12');guide.setAttribute('y',String(8+i*pitch));guide.setAttribute('width',String(result.widthPx));guide.setAttribute('height',String(sceneMetrics.height*2));guide.setAttribute('fill','none');guide.setAttribute('stroke','#55708f');svg.append(guide);
   for(const g of row.glyphs){const rect=document.createElementNS(ns,'rect');for(const [k,v]of Object.entries({x:g.x+12,y:8+i*pitch,width:g.width,height:g.height*2}))rect.setAttribute(k,String(v));rect.setAttribute('fill',g.placeholder?'#563951':'#1b394d');rect.setAttribute('stroke','#355969');svg.append(rect);const text=document.createElementNS(ns,'text');text.textContent=g.text;for(const [k,v]of Object.entries({x:g.x+12,y:8+i*pitch+g.height*2-3,fill:'#f2f5f9','font-size':g.height*2,textLength:g.width,lengthAdjust:'spacingAndGlyphs'}))text.setAttribute(k,String(v));if(atlas.glyphs[g.text]){const cell=document.createElementNS(ns,'svg');for(const [k,v]of Object.entries({x:g.x+12,y:8+i*pitch,width:g.width,height:g.height*2,viewBox:`${atlas.glyphs[g.text][0]} ${atlas.glyphs[g.text][1]} 24 24`,preserveAspectRatio:'none'}))cell.setAttribute(k,String(v));const image=document.createElementNS(ns,'image');image.setAttribute('href','./assets/'+atlas.image);image.setAttribute('width',String(atlas.width));image.setAttribute('height',String(atlas.height));cell.append(image);svg.append(cell);}else svg.append(text);}
  });$('geometry').replaceChildren(svg);return result;
 }catch(e){$('error').textContent=`${e.code||'error'}: ${e.message}`;$('output').textContent='';$('geometry').replaceChildren();$('rows').replaceChildren();$('json').textContent='';return null;}
}
$('run').onclick=()=>{run();$('parity').textContent='已使用浏览器本地共享核心排版。';};
$('compare').onclick=async()=>{const local=run();if(!local)return;try{const response=await fetch('./api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request())});const remote=await response.json();if(!remote.ok)throw new Error(remote.error.message);const equal=JSON.stringify(local)===JSON.stringify(remote.result);$('parity').textContent=equal?'通过：浏览器与后端返回的完整 JSON 逐字段一致（文本、坐标、宽高、控制符、宽度）。':'失败：前后端结果不同。';}catch(e){$('parity').textContent='比较失败：'+e.message;}};
$('sample').onclick=()=>{$('text').value=samples[select.value]||samples.prose;if($('escaped').checked)$('text').value=$('text').value.replace(/\n/g,'\\n');run();};select.onchange=()=>{updateContract();$('sample').click();};updateContract();run();

$('text').oninput=()=>{$('parity').textContent='输入已改变，请重新排版或比较。';};

$('ruler').onclick=()=>{const s=getScene(select.value);if(s.kind!=='prose')return;$('text').value='　'+'测'.repeat(s.columns*3-1);run();};
