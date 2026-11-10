import {measure} from '/Users/nate/Super-Robot-Wars-Z/srwz-zh/shared/text-layout/engine.mjs';
import fs from 'fs';
const o={typography:'proportional',chinesePunctuation:'compact'};
const inp=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const out=inp.map(t=>{try{const r=measure(t,'battle',o);return r.rows.map(x=>({text:x.text,adv:x.advancePx,occ:x.occupiedPx,g:x.glyphs.map(g=>[g.text,g.x,g.width,g.height,g.advance,g.yOffset||0])}))}catch(e){return {err:String(e.message)}}});
fs.writeFileSync(process.argv[3],JSON.stringify(out));
