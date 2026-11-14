// Story / map dialogue line breaks that follow the Japanese rows and reviewed breaks.
// Library + CLI for tools/text_layout/relayout_story_breaks.py:
//   node story_breaks.mjs INPUT.json OUTPUT.json
// INPUT rows: {id, zh, jp, old, scene, links, reviewed:[...], opinion:[text]}.
// Decision order per record (logical text never changes, only row breaks):
//   1. choice / aligned rows (no continuation indent) keep their stored structure;
//   1b. a Special Disc record bound to a main-game record takes that record's breaks;
//   2. a reviewed record keeps the breaks it had before the 2026-11-08 mechanical reflow,
//      or the breaks of a review opinion that edited the breaks themselves;
//      a break-only opinion (r.break_only) outranks the earlier breaks;
//   3. earlier breaks with the Japanese row count stay (mid-word cuts move to the mapped cut);
//   4. otherwise Japanese breaks map onto the matching Chinese punctuation, rows are not
//      merged just because they would fit, and an overflowing row splits at a word boundary;
//   5. when only a forced split is left, the earlier stored breaks win if they still fit.
import {measure,validate,getScene} from '../../shared/text-layout/engine.mjs';
import {contracts} from '../../shared/text-layout/contracts.mjs';
const SEG=new Intl.Segmenter('zh',{granularity:'word'});
const TERMS=getScene('story').protectedTerms.filter(t=>t.length>1);
const ATTACH_LEFT=new Set([...'了的着过吗呢吧啊呀嘛么们地得']);
const PUNCT=/[。！？，、…—；：!?”’）」』]/;
// Legal cut offsets inside a body: word boundaries, not inside protected terms, not splitting single-char runs.
function cutPoints(body){
  const segs=[...SEG.segment(body)];const pts=new Map();let off=0;
  for(let i=0;i<segs.length-1;i++){off+=segs[i].segment.length;const L=segs[i].segment,Rr=segs[i+1].segment;
    const punctLeft=PUNCT.test(L.at(-1));
    if(!punctLeft){
      if(PUNCT.test(Rr[0]))continue;
      if(ATTACH_LEFT.has(Rr[0]))continue;
      if(L.length===1&&Rr.length===1&&!/[A-Za-z0-9]/.test(L+Rr))continue;
    }
    if(contracts.forbiddenStart.includes(Rr[0])||contracts.forbiddenEnd.includes(L.at(-1)))continue;
    if(L.at(-1)==='$'||/[·・]/.test(L.at(-1)+Rr[0])||(/[A-Za-z0-9\-.']/.test(L.at(-1))&&/[A-Za-z0-9\-.']/.test(Rr[0])))continue;
    pts.set(off,punctLeft?0:1);
  }
  for(const t of TERMS){let i=body.indexOf(t);while(i>=0){for(let k=i+1;k<i+t.length;k++)pts.delete(k);i=body.indexOf(t,i+1);}}
  return pts;
}
function splitRow(prefix,body,suffixRows,k,r){
  // prefix: rows before (array), body: text of one row to split into k rows; returns best full text or null
  const pts=[...cutPoints(body)];let best=null;
  const combos=k===2?pts.map(p=>[p]):pts.flatMap((p,i)=>pts.slice(i+1).map(q=>[p,q]));
  for(const c of combos){const cuts=c.map(x=>x[0]);const parts=[];let a=0;for(const x of [...cuts,body.length]){parts.push(body.slice(a,x));a=x;}
    const rows=[...prefix,...parts.map((p,j)=>(prefix.length||j)?'　'+p:p),...suffixRows];const t=rows.join('\n');const w=fits(t,r);if(!w)continue;
    const ws=w.slice(prefix.length,prefix.length+parts.length),mean=ws.reduce((x,y)=>x+y,0)/ws.length;
    const cost=ws.reduce((s,x)=>s+(x-mean)**2,0)/400+c.reduce((s,x)=>s+x[1]*30,0);
    if(!best||cost<best.cost)best={cost,t,w};}
  return best;
}
import fs from 'fs';
const LIM={story:483,story_map:420,sp_story_map:420};
const OPT=r=>({typography:'proportional',chinesePunctuation:'compact',keywordLinks:!!r.links});
const logical=t=>t.replace(/\n[　 ]*/g,'');
// A row may open with an ellipsis (user rule 2026-11-13), so punctuation followed by an ellipsis is two
// groups: the break lands before the ellipsis that opens the next Japanese row.
const PJ=/[。！？!?、]+(?=…)|[。！？、…―!?]+[」』）]*/g, PZ=/[。！？!?，、]+(?=…)|[。！？，、…—；：!?]+[”’）」』]*/g;
const HARD=new Set([...'。！？!?…']);
const WEAK={'。':0,'！':0,'？':0,'…':0,'!':0,'?':0,'；':1,'：':1,'—':1,'，':2,'、':4};
function groups(t,re,stutter=false){const o=[];for(const m of t.matchAll(re)){const e=m.index+m[0].length;if(e>=t.length)continue;
  if(stutter&&m[0][0]==='、'&&m.index<=2)continue;o.push({pos:e,ch:m[0][0],w:WEAK[m[0][0]]??3});}return o;}
function compose(zl,cuts){const c=[...new Set(cuts)].sort((a,b)=>a-b);const parts=[];let a=0;for(const x of [...c,zl.length]){parts.push(zl.slice(a,x));a=x;}return parts[0]+parts.slice(1).map(p=>'\n　'+p).join('');}
function fits(t,r){try{const m=measure(t,r.scene,OPT(r));if(m.rows.length>3)return null;const w=m.rows.map(x=>x.fitPx??x.occupiedPx);if(w.some(x=>x>LIM[r.scene]))return null;
  const v=validate(t,r.scene,OPT(r));if(!v.valid)return null;return w;}catch(e){return null;}}
function jpBreaks(jp){const rows=jp.split('\n');const out=[];let p=0;const jl=logical(jp);
  for(let i=0;i<rows.length-1;i++){p+=(i?rows[i].replace(/^[　 ]+/,''):rows[i]).length;out.push({off:p,frac:p/jl.length});}return out;}
function propose(r){
  const zh=r.zh, jrows=r.jp.split('\n');
  if(zh.split('\n').slice(1).some(x=>!x.startsWith('　'))||jrows.slice(1).some(x=>!x.startsWith('　')))return {cat:'choice',text:zh};
  const zl=logical(zh), jl=logical(r.jp), jb=jpBreaks(r.jp);
  const jg=groups(jl,PJ).map(g=>g.pos), zgAll=groups(zl,PZ), zg=zgAll.map(g=>g.pos), zgS=groups(zl,PZ,true);
  const jh=jg.filter(p=>HARD.has(jl[p-1])||'」』）'.includes(jl[p-1])), zh_h=zg.filter(p=>HARD.has(zl[p-1])||'”’）」』'.includes(zl[p-1]));
  const strong=[],optional=[];let unmapped=0;
  const typ=(c)=>HARD.has(c)||'；：—―'.includes(c)?'h':'s';
  const jT=jg.map(p=>typ(jl.slice(0,p).replace(/[」』）”’]+$/,'').at(-1))), zT=zgAll.map(g=>typ(g.ch));
  for(const b of jb){
    const k=jg.indexOf(b.off);
    if(k>=0){
      const T=jT[k];
      if(jg.length===zg.length&&zT[k]===T){strong.push(zg[k]);continue;}
      const js=jg.filter((_,i)=>jT[i]===T), zs=zg.filter((_,i)=>zT[i]===T);
      if(js.length===zs.length&&js.length){strong.push(zs[js.indexOf(b.off)]);continue;}
      let near=null;zg.forEach((p,i)=>{if(zT[i]!==T)return;const d=Math.abs(p/zl.length-b.frac);if(d<=0.2&&(!near||d<near.d))near={p,d};});
      if(near){strong.push(near.p);continue;}
    }
    // particle or unmatched punctuation: nearest zh punctuation within 15% of the line
    let best=null;for(const g of zgS){const d=Math.abs(g.pos/zl.length-b.frac);if(d<=0.15&&(!best||d+g.w*0.02<best.d))best={pos:g.pos,d:d+g.w*0.02,w:g.w};}
    if(best)optional.push(best);else unmapped++;
  }
  const tag=(strong.length===jb.length?'jp_exact':(strong.length||optional.length)?'jp_partial':'jp_none');
  // try strong + optional, then drop optional by weakness
  let opts=[...optional].sort((a,b)=>a.w-b.w);
  for(let n=opts.length;n>=0;n--){
    const cuts=[...strong,...opts.slice(0,n).map(o=>o.pos)];
    const t=compose(zl,cuts);const w=fits(t,r);
    if(w)return {cat:tag,text:t,widths:w};
    // a row overflows: split it at word boundaries (punctuation preferred), keeping total rows <= 3
    const rows=t.split('\n');if(rows.length>=3)continue;
    try{const m=measure(t,r.scene,OPT(r));const bad=m.rows.map((x,i)=>(x.fitPx??x.occupiedPx)>LIM[r.scene]?i:-1).filter(i=>i>=0);
      if(bad.length!==1)continue;const i=bad[0];
      for(let k=2;k<=3-rows.length+1;k++){const res=splitRow(rows.slice(0,i),rows[i].replace(/^[　 ]+/,''),rows.slice(i+1),k,r);if(res)return {cat:tag+'+split',text:res.t,widths:res.w};}
    }catch(e){}
  }
  // fallback: whole record, balanced
  for(const k of [2,3]){const res=splitRow([],zl,[],k,r);if(res)return {cat:'split_only',text:res.t,widths:res.w};}
  return {cat:'current',text:zh};
}
const fitsScene=(t,r)=>{try{const m=measure(t,r.scene,OPT(r));if(m.rows.length>3)return false;if(m.rows.some(x=>(x.fitPx??x.occupiedPx)>LIM[r.scene]))return false;return validate(t,r.scene,OPT(r)).valid;}catch(e){return false;}};
const rows=t=>t.split('\n').length;
const indented=t=>!t.split('\n').slice(1).some(x=>!x.startsWith('　'));
const cutsOf=t=>{const o=[];let p=0;t.split('\n').forEach((x,i,A)=>{p+=(i?x.slice(1):x).length;if(i<A.length-1)o.push(p);});return o;};
function decide(r){
  const L=logical(r.zh);let d;
  const structured=!indented(r.zh)||!indented(r.jp||'');
  const oldOk=r.old&&logical(r.old)===L&&indented(r.old)&&fitsScene(r.old,r);
  const legal=t=>{const pts=cutPoints(L);return cutsOf(t).every(c=>pts.has(c));};
  if(structured||!r.jp)d={cat:'keep_structured',text:r.zh};
  else if(r.twin&&logical(r.twin)===L&&indented(r.twin)&&fitsScene(r.twin,r))d={cat:'main_twin',text:r.twin};
  else if(r.break_only?.length&&indented(r.break_only[0])&&!/[·・$]\n|\n　[·・]/.test(r.break_only[0])&&fitsScene(r.break_only[0],r))d={cat:'reviewed_breaks',text:r.break_only[0]};
  else if(r.reviewed.length&&oldOk)d={cat:'reviewed_old',text:r.old};
  else if(r.opinion.length&&indented(r.opinion[0])&&!/[·・$]\n|\n　[·・]/.test(r.opinion[0])&&fitsScene(r.opinion[0],r))d={cat:'reviewed_opinion',text:r.opinion[0]};
  else{
    const p=propose(r);
    if(oldOk&&rows(r.old)===rows(r.jp)){
      if(p.text!==r.old&&rows(p.text)===rows(r.old)&&p.cat.startsWith('jp_')&&!p.cat.includes('split')&&!legal(r.old))d={cat:'old_midword_fixed',text:p.text,alt:r.old};
      else d={cat:'old_matches_jp',text:r.old};}
    else if(oldOk&&(p.cat.includes('split')||p.cat==='jp_none'||!p.cat.startsWith('jp_')))d={cat:'old_kept',text:r.old};
    else d={cat:p.cat,text:p.text};
  }
  // Readers expect the ellipsis that opens a Japanese row to open the Chinese row too, reviewed
  // records included: earlier tooling could only hang it at the end of the previous row.
  if(d.cat!=='keep_structured'&&/\n　?…/.test(r.jp||'')){
    const rs=d.text.split('\n');let moved=false;
    for(let i=0;i<rs.length-1;i++){const m=rs[i].match(/^(.*[。！？!?，、”’）])(…+)$/);
      if(m&&!rs[i+1].startsWith('　…')){rs[i]=m[1];rs[i+1]='　'+m[2]+rs[i+1].slice(1);moved=true;}}
    if(moved&&fitsScene(rs.join('\n'),r))d={...d,text:rs.join('\n'),ellipsis:true};
  }
  if(logical(d.text)!==L)throw new Error(r.id);
  return d;
}
export {decide,propose,cutPoints,logical};
import {fileURLToPath} from 'url';
if(process.argv[1]===fileURLToPath(import.meta.url)){
  const out={},count={};
  for(const r of JSON.parse(fs.readFileSync(process.argv[2],'utf8'))){const d=decide(r);out[r.id]=d;count[d.cat]=(count[d.cat]||0)+1;}
  fs.writeFileSync(process.argv[3],JSON.stringify(out));console.log(JSON.stringify(count));
}
