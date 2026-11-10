import fs from 'fs';
const base=await import('/Users/nate/Super-Robot-Wars-Z/srwz-zh/shared/text-layout/engine.mjs');
const wide=await import(process.argv[2]+'/engine.mjs');
const o={typography:'proportional',chinesePunctuation:'compact',maxLines:3};
const dir='corpus/zh/story-dialogue/';
let total=0,multi=0,opener=0,row0Over=0,anyOver=0,relayoutFail=0,relayoutMoreRows=0,relayoutSameRows=0,singleOver=0,measureErr=0;const ex=[];
const t0=Date.now();
for(const f of fs.readdirSync(dir).filter(f=>f.endsWith('.json'))){
  for(const e of JSON.parse(fs.readFileSync(dir+f,'utf8')).entries){
    const t=e.translation; if(typeof t!=='string'||!t)continue; total++;
    const first=[...t.replace(/<[^>]*>/g,'')][0];
    if(!'“（'.includes(first))continue; opener++;
    let cur,w;
    try{cur=base.measure(t,'story',o);w=wide.measure(t,'story',o)}catch(x){measureErr++;continue}
    const isMulti=cur.rows.length>1; if(isMulti)multi++;
    const over0=cur.rows[0].occupiedPx+5>483;           // line-initial opener only
    const overAny=w.rows.some(r=>r.occupiedPx>483);      // every “（ in the scene full width
    if(!isMulti){ if(over0)singleOver++; continue }
    if(over0)row0Over++;
    if(overAny)anyOver++;
    if(over0){ // would a re-layout still fit three rows?
      const logical=t.split('\n').map((l,i)=>i?l.replace(/^[　 ]+/,''):l).join('');
      try{const r=wide.layout(logical,'story',o); if(r.rows.length>cur.rows.length)relayoutMoreRows++; else relayoutSameRows++;}
      catch(x){relayoutFail++; if(ex.length<5)ex.push(e.id+' '+t.replace(/\n/g,'/'))}
    }
  }
}
console.log(JSON.stringify({total,startsWithOpener:opener,multiRow:multi,lineInitial_row0Overflow:row0Over,sceneWide_anyRowOverflow:anyOver,singleRowOverflow:singleOver,relayout:{sameRows:relayoutSameRows,moreRows:relayoutMoreRows,noLegalLayout:relayoutFail},measureErr,seconds:(Date.now()-t0)/1000,ex},null,1));
