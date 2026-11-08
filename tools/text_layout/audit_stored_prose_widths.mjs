import fs from 'node:fs';
import {measure,getScene} from '../../shared/text-layout/engine.mjs';
import {contracts} from '../../shared/text-layout/contracts.mjs';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const root=fileURLToPath(new URL('../../',import.meta.url)).replace(/\/$/,'');
const inputs={};
const hashFile=file=>{const raw=fs.readFileSync(root+'/'+file);inputs[file]=createHash('sha256').update(raw).digest('hex');return raw;};
for(const f of ['engine.mjs','contracts.mjs','proportional-selection.mjs','proportional-metrics.mjs'])hashFile('shared/text-layout/'+f);
const results=[];
for(const [file,scene] of [['corpus/zh/menu/stage-overviews.json','main_flow'],['corpus/zh/summary.json','main_scroll']]){
 const entries=JSON.parse(hashFile(file)).entries;
 const summary={scene,entries:0,overflow:[],nonfinalRows:0,fillSum:0,minimumFill:1,below90:[],widths:{}};
 for(const e of entries){
  if(!e.translation)continue;
  const options={typography:'proportional',chinesePunctuation:'compact',resourceId:e.id};
  const spec=getScene(scene==='main_scroll'?(contracts.resourceSceneOverrides?.[e.id]||scene):scene);
  const result=measure(e.translation,scene,options);
  const limit=spec.widthPx;
  summary.entries++;summary.widths[limit]=(summary.widths[limit]||0)+1;
  for(let i=0;i<result.rows.length;i++){
   const r=result.rows[i];
   if(r.occupiedPx>limit)summary.overflow.push({id:e.id,row:i,width:r.occupiedPx,limit});
   if(!r.text.trim()||i===result.rows.length-1||!result.rows[i+1].text.trim()||/^[ 　]/.test(result.rows[i+1].text))continue;
   const fill=r.occupiedPx/limit;summary.nonfinalRows++;summary.fillSum+=fill;summary.minimumFill=Math.min(summary.minimumFill,fill);
   if(fill<.9)summary.below90.push({id:e.id,row:i,width:r.occupiedPx,limit,text:r.text});
  }
 }
 summary.meanNonfinalFill=summary.fillSum/summary.nonfinalRows;delete summary.fillSum;results.push(summary);
}
fs.writeFileSync(root+'/work/review/tag-free-promotion-20261108/stored-prose-widths.json',JSON.stringify({kind:'static-shared-engine-stored-row-audit',inputs,paragraphTails:'Excluded before blank rows, indented paragraph starts and end of resource',results},null,2)+'\n');
console.log(JSON.stringify(results.map(({below90,...x})=>({...x,below90:below90.length})),null,2));
if(results.some(r=>r.overflow.length))process.exitCode=1;
