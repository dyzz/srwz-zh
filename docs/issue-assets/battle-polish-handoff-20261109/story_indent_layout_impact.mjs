// How many dialogue lines the row solver breaks differently once the continuation
// indent is budgeted at its drawn width (16px) instead of a full cell (21px).
//   node story_indent_layout_impact.mjs
import fs from 'fs';
import {layout,validate} from '../../../shared/text-layout/engine.mjs';
const root=new URL('../../../',import.meta.url).pathname;
const o={typography:'proportional',chinesePunctuation:'compact',maxLines:3},legacy={...o,continuationIndent:'fullwidth'};
const sets={main:fs.readdirSync(root+'corpus/zh/story-dialogue').filter(f=>f.endsWith('.json')).map(f=>'corpus/zh/story-dialogue/'+f),
 sp:['corpus/zh/special-disc/story-dialogue.json','corpus/zh/special-disc/challenge-dialogue.json']};
const out={};
for(const [name,files] of Object.entries(sets)){
 const r={entries:0,openerMultiRow:0,storedInvalid:0,solverDiffers:0,fewerRows:0,storedDiffersFromSolver:0,skipped:0,examples:[]};
 for(const f of files)for(const e of JSON.parse(fs.readFileSync(root+f,'utf8')).entries){
  const t=e.translation;if(typeof t!=='string'||!t)continue;r.entries++;
  if(!'“‘（《【'.includes(t[0])||!/\n　[^　 \n]/.test(t))continue;r.openerMultiRow++;
  try{if(!validate(t,'story',o).valid)r.storedInvalid++}catch(x){r.skipped++;continue}
  const logical=t.split('\n').map((l,i)=>i?l.replace(/^[　 ]+/,''):l).join('');
  let a,b;try{a=layout(logical,'story',o);b=layout(logical,'story',legacy)}catch(x){r.skipped++;continue}
  if(a.text!==b.text){r.solverDiffers++;if(a.rows.length<b.rows.length)r.fewerRows++;if(r.examples.length<3)r.examples.push({id:e.id,legacy:b.text.replace(/\n/g,'/'),current:a.text.replace(/\n/g,'/')})}
  if(a.text!==t)r.storedDiffersFromSolver++;
 }
 out[name]=r;
}
console.log(JSON.stringify(out,null,1));
