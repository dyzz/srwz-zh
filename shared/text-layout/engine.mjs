/** Pure SRWZ layout core. No DOM, filesystem, process, or font measurement APIs. */
import { contracts } from './contracts.mjs';
export const version = '1.1.0';
export const sceneIds = Object.freeze(Object.keys(contracts.scenes));
export class LayoutError extends Error {
  constructor(code, message, details = {}) { super(message); this.name = 'LayoutError'; this.code = code; this.details = details; }
}
const fail = (code, message, details) => { throw new LayoutError(code, message, details); };
const hex = n => n.toString(16).toUpperCase().padStart(2, '0');
const safeHeight = n => n === 10 ? 0x8A : n;
const controlRE = new RegExp(contracts.controls, 'y');
const scopeRE = new RegExp(`<z>([${contracts.compactCharacters}]+)</z>`, 'y');
const nativeScopeRE = new RegExp('<width:[0-9A-Fa-f]{2}><space:[0-9A-Fa-f]{2}>(?:<height:[0-9A-Fa-f]{2}>)?' +
  '(?:[A-Za-z0-9Ａ-Ｚａ-ｚ０-９ .,:：．_\x27/／＋+％%~～〜×÷±＝=　－−·《》（）-]|<height:[0-9A-Fa-f]{2}>)+?' +
  '(?:<width:[0-9A-Fa-f]{2}><space:[0-9A-Fa-f]{2}>|<space:[0-9A-Fa-f]{2}><width:[0-9A-Fa-f]{2}>)(?:<height:[0-9A-Fa-f]{2}>)?', 'y');
const latinRE = /[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+(?:[.·_-][A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+)*[ 　]?/y;
const numberRE = /(?:第[0-9０-９]+(?:话|章|关|幕|次|号|代|阶段|批)?|[0-9０-９]+(?:[.,][0-9０-９]+)*(?:%|％|岁|年|月|日|时|分|秒|米|公里|千米|海里|节|话|号|机|艘|人|倍|层|级|点|个)?)/y;
function match(re, text, offset) { re.lastIndex = offset; return re.exec(text); }
export function getScene(id) {
  const value = typeof id === 'string' && Object.hasOwn(contracts.scenes, id) ? contracts.scenes[id] : null;
  if (!value) fail('unknown_scene', `Unknown scene: ${id}`, { allowed: sceneIds });
  // Do not expose mutable configuration shared by different requests.
  return { ...value, compact: { ...value.compact }, protectedTerms: [...value.protectedTerms] };
}
function sceneOf(value) { return getScene(typeof value === 'string' ? value : value?.id); }
function effectiveScene(id,options={}) {
  const resolved=id==='main_scroll' ? contracts.resourceSceneOverrides?.[options?.resourceId] : null;
  return sceneOf(resolved||id);
}
function normalize(text) {
  if (typeof text !== 'string' || text.length > 12000) fail('input', 'Text must be a string of at most 12000 UTF-16 code units');
  if (/[\u0000-\u0009\u000B-\u001F\u007F]/.test(text)) fail('input', 'Non-text control bytes are not author text');
  return text.replace(/\r\n?/g, '\n');
}
function checkOptions(options,scene) {
  if(!options||typeof options!=='object'||Array.isArray(options))fail('options','Expected an options object');
  for(const key of ['preserveLineCount','escapedNewlines','protectWords','keywordLinks'])if(options[key]!==undefined&&typeof options[key]!=='boolean')fail('options',`${key} must be boolean`);
  if(options.maxLines!==undefined&&(!Number.isInteger(options.maxLines)||options.maxLines<1||options.maxLines>12000||(scene.maxLines!==null&&options.maxLines>scene.maxLines)))fail('options','maxLines exceeds native scene or input limits');
  if(options.placeholderCells!==undefined&&(!Number.isInteger(options.placeholderCells)||options.placeholderCells<1||options.placeholderCells>64))fail('options','Invalid placeholder reservation');
  if(options.protectedTerms!==undefined&&(!Array.isArray(options.protectedTerms)||options.protectedTerms.length>10000||options.protectedTerms.some(t=>typeof t!=='string'||!t.length||t.length>1000||/[\r\n]/.test(t))))fail('options','Invalid protected terms');
  if(options.packing!==undefined&&!['max_width','balanced_width'].includes(options.packing))fail('options','Unknown line packing');
  if(options.resourceId!==undefined&&(typeof options.resourceId!=='string'||options.resourceId.length>256||/[\r\n]/.test(options.resourceId)))fail('options','Invalid resource ID');
  if(options.initialState!==undefined)fail('options','Initial font state belongs to the selected scene');
}
function initial(scene) { return { width: scene.width, height: scene.height, step: scene.step }; }
function scopeNative(run, scene) {
  const m = scene.compact;
  let active = null, current = /[0-9０-９]/.test(run.match(/[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]/)?.[0] || '') ? 'digit' : 'letter';
  let body = '', keyword = false;
  for (const ch of run) {
    keyword = ch === '《' || keyword && ch !== '》';
    if (!(keyword && active !== null)) {
      if (/[0-9０-９]/.test(ch)) current = 'digit';
      else if (/[A-Za-zＡ-Ｚａ-ｚ]/.test(ch)) current = 'letter';
    }
    if (active !== m[current]) { active = m[current]; body += `<height:${hex(safeHeight(active))}>`; }
    body += ch;
  }
  const width = `<width:${hex(m.restore_width)}>`, space = `<space:${hex(m.restore_space)}>`;
  return `<width:${hex(m.width)}><space:${hex(m.space)}>${body}` +
    (/[％%]$/.test(run) ? space + width : width + space) + `<height:${hex(safeHeight(m.restore_height))}>`;
}
export function expandCompact(text, sceneId) {
  const scene = sceneOf(sceneId); text = normalize(text);
  let out = '', i = 0;
  while (i < text.length) {
    if (text.startsWith('<z>', i)) {
      const m = match(scopeRE, text, i);
      if (!m) fail('compact_scope', 'Malformed, nested, or unsupported compact scope', { offset: i });
      out += scopeNative(m[1], scene); i += m[0].length;
    } else {
      if (text.startsWith('</z>', i)) fail('compact_scope', 'Unmatched compact closing tag', { offset: i });
      const ch = String.fromCodePoint(text.codePointAt(i)); out += ch; i += ch.length;
    }
  }
  return out;
}
function rejectDynamic(text) {
  if (/＜\/?ｔｍ＞|<\/?tm>|^@[+-]?[0-9<]|\[[+-]?(?:[0-9]|<(?:color|width|height|space):)/.test(text))
    fail('owner_contract', 'Dynamic template, repeat, or square parameter needs an owner-specific contract');
}
function keywordSpans(text) {
  let open = -1; const spans = new Map();
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '《') { if (open >= 0) fail('keyword', 'Nested keyword link'); open = i; }
    if (text[i] === '》') {
      if (open < 0 || open + 1 === i) fail('keyword', 'Unmatched or empty keyword link');
      spans.set(open, text.slice(open, i + 1)); open = -1;
    }
  }
  if (open >= 0) fail('keyword', 'Unclosed keyword link');
  return spans;
}
function measureRow(text, scene, start, options) {
  text = expandCompact(text, scene.id); rejectDynamic(text);
  if (/[\r\n]/.test(text)) fail('input', 'Row measurement accepts one physical row');
  if (options.keywordLinks) keywordSpans(text);
  let state = { ...start }, x = 0, right = 0, i = 0; const glyphs = [];
  while (i < text.length) {
    const m = match(controlRE, text, i);
    if (m) {
      const token = m[0], dim = /^<(width|space|height):([0-9A-Fa-f]{2})>$/.exec(token);
      if (dim) {
        let v = parseInt(dim[2], 16);
        if (dim[1] === 'height') { if (v >= 0x8A && v <= 0x8E) v &= 127; else if (v === 10 || v < 1 || v > 63) fail('dimension', 'Height 10 requires native 8A encoding; invalid height parameter'); state.height = v; }
        else {
          if (v < 1 || v > 63) fail('dimension', `Invalid renderer dimension: ${token}`);
          state[dim[1] === 'space' ? 'step' : 'width'] = v;
        }
      } else if (/^<[^:]+:/.test(token) && !/^<(?:color|3[1-5]):[0-9A-Fa-f]{2}>$/.test(token)) {
        fail('control', `Unregistered native tag: ${token}`);
      } else {
        const cells = /^[%$]/.test(token) ? (options.placeholderCells ?? 6) : /^<[+-]?[0-9<]/.test(token) ? 1 : 0;
        if (cells) {
          glyphs.push({ text: token, x, width: (cells - 1) * state.step + state.width, height: state.height, advance: cells * state.step, placeholder: true });
          right = Math.max(right, x + (cells - 1) * state.step + state.width); x += cells * state.step;
        }
      }
      i += token.length; continue;
    }
    if (/^@?</.test(text.slice(i)) || /^\{[0-9A-Za-z]/.test(text.slice(i)) || /^\$[A-Za-z]/.test(text.slice(i)) || /^%[-+#0.*$0-9A-Za-z]/.test(text.slice(i)))
      fail('control', 'Unrecognized control syntax', { offset: i });
    const ch = String.fromCodePoint(text.codePointAt(i)); i += ch.length;
    if (options.keywordLinks && (ch === '《' || ch === '》')) continue;
    glyphs.push({ text: ch, x, width: state.width, height: state.height, advance: state.step, placeholder: false });
    if (ch !== ' ' && ch !== '　') right = Math.max(right, x + state.width);
    x += state.step;
  }
  return { text, advancePx: x, occupiedPx: Math.max(x, right), glyphs, state };
}
export function measure(text, sceneId, options = {}) {
  const scene = effectiveScene(sceneId,options); checkOptions(options,scene); text = normalize(text);
  if (options.escapedNewlines) text = text.replace(/\\n/g, '\n');
  let state = initial(scene);
  const rows = text.split('\n').map(line => {
    const r = measureRow(line, scene, state, options); state = r.state;
    return { text: line, advancePx: r.advancePx, occupiedPx: r.occupiedPx, glyphs: r.glyphs };
  });
  return { scene: scene.id, rows, state };
}
const termCache = new Map();
function termsFor(scene, extra) {
  const cacheKey = extra?.length ? null : scene.id;
  if (cacheKey && termCache.has(cacheKey)) return termCache.get(cacheKey);
  const terms = [...new Set([...scene.protectedTerms, ...(extra || [])])].sort((a,b) => b.length-a.length || (a<b?-1:1));
  const index = new Map(); for (const term of terms) { const c=term[0]; if (!index.has(c)) index.set(c,[]); index.get(c).push(term); }
  if (cacheKey) termCache.set(cacheKey,index); return index;
}
function visible(text) { return text.replace(/<\/?z>/g,'').replace(new RegExp(contracts.controls,'g'),m => /^[%$]/.test(m)?'名':''); }
function controlledTerms(text, termIndex, options) {
  const result=new Map();
  if(options.protectWords===false||!/<(?:z>|width:|space:)/.test(text))return result;
  const plain=visible(text), spans=[];
  for(let i=0;i<text.length;){const m=match(scopeRE,text,i)||match(nativeScopeRE,text,i);if(m){spans.push([i,i+m[0].length]);i+=m[0].length;}else i++;}
  const dimensions='(?:</?z>|<(?:width|space|height):[0-9A-Fa-f]{2}>)*';
  const escape=s=>Array.from(s).map(c=>'^$.*+?()[]{}|'.includes(c)||c.charCodeAt(0)===92?String.fromCharCode(92)+c:c).join('');
  for(const terms of termIndex.values())for(const term of terms){
    if(!plain.includes(term))continue;
    const re=new RegExp(dimensions+Array.from(term).map(escape).join(dimensions)+dimensions,'g');
    for(const m of text.matchAll(re)){
      const start=m.index,end=start+m[0].length;
      if(!/<(?:z>|width:|space:)/.test(m[0]))continue;
      if(spans.some(([a,b])=>start<b&&a<end&&!(start<=a&&b<=end)))continue;
      if(!result.has(start)||result.get(start).length<m[0].length)result.set(start,m[0]);
    }
  }
  return result;
}
function tokensFor(text, scene, startState, options) {
  rejectDynamic(text); const terms = termsFor(scene, options.protectedTerms);
  const links = options.keywordLinks ? keywordSpans(text) : new Map();
  const controlled=controlledTerms(text,terms,options);
  const tokens=[]; let offset=0, state={...startState}, pending='', pendingBefore=null;
  while(offset<text.length) {
    let value='', atomic=false;
    const scope=match(scopeRE,text,offset), native=match(nativeScopeRE,text,offset), control=match(controlRE,text,offset);
    if(controlled.has(offset)){value=controlled.get(offset);atomic=true;}
    else if(scope) {value=scope[0];atomic=true;}
    else if(native) {value=native[0];atomic=true;}
    else if(links.has(offset)){value=links.get(offset);atomic=true;}
    else if(control){value=control[0];atomic=true;}
    else {
      let candidates=[];
      if(options.protectWords !== false) {
        const term=(terms.get(text[offset])||[]).find(t=>text.startsWith(t,offset));if(term)candidates.push(term);
        for(const re of [latinRE,numberRE]){const m=match(re,text,offset);if(m)candidates.push(m[0]);}
      }
      if(text.startsWith('……',offset)||text.startsWith('——',offset)){candidates.push(text.slice(offset,offset+2));atomic=true;}
      candidates.sort((a,b)=>b.length-a.length||(a>b?-1:1));
      value=candidates[0]||String.fromCodePoint(text.codePointAt(offset));
    }
    const before=pendingBefore||{...state}; const extent=measureRow(value,scene,state,options);state=extent.state;offset+=value.length;
    if(!extent.advancePx){pendingBefore=before;pending+=value;continue;}
    const token={text:pending+value,advance:extent.advancePx,occupied:extent.occupiedPx,before,after:{...state},atomic,visible:visible(value)};
    pending='';pendingBefore=null;
    if(token.occupied>scene.widthPx && !atomic && Array.from(value).length>1) {
      tokens.push(...tokensFor(value,scene,before,{...options,protectWords:false}));
    } else tokens.push(token);
  }
  if(pending){if(tokens.length){tokens.at(-1).text+=pending;tokens.at(-1).after={...state};}else tokens.push({text:pending,advance:0,occupied:0,before:startState,after:state,atomic:true,visible:''});}
  return tokens;
}
function legal(tokens,end) {
  if(end===tokens.length)return true;
  const left=Array.from(tokens[end-1].visible).at(-1), right=Array.from(tokens[end].visible)[0];
  return !contracts.forbiddenEnd.includes(left||'\0')&&!contracts.forbiddenStart.includes(right||'\0');
}
function partition(text,scene,options,firstIndent='',continuationIndent='',exactRows=null,maxRows=scene.maxLines) {
  const start=options.initialState||initial(scene), tokens=tokensFor(text,scene,start,options), n=tokens.length;
  if(!n)return [firstIndent];
  if(n>6000)fail('complexity','Too many layout tokens');
  const prefix=[0];for(const t of tokens)prefix.push(prefix.at(-1)+t.advance);
  const range=(a,b)=>{let edge=0;for(let i=a;i<b;i++)edge=Math.max(edge,prefix[i]-prefix[a]+tokens[i].occupied);return Math.max(prefix[b]-prefix[a],edge);};
  // Prefix-constrained legal edges are finite, cached once, and independent of row count.
  const edges=Array.from({length:n},()=>[]);
  for(let a=0;a<n;a++)for(let b=a+1;b<=n;b++){
    const w=range(a,b);if(w>scene.widthPx)break;if(legal(tokens,b))edges[a].push({end:b,width:w});
  }
  const ceiling=Math.min(maxRows??n,n), minimum=exactRows??Math.max(1,Math.ceil(prefix[n]/scene.widthPx)), limit=exactRows??ceiling;
  if(!Number.isInteger(ceiling)||ceiling<1||!Number.isInteger(minimum)||minimum<1||limit>ceiling)fail('rows','Invalid physical row budget');
  for(let rows=minimum;rows<=limit;rows++){
    const memo=new Map();
    const balanced=(options.packing??scene.packing)==='balanced_width';
    const totalAdvance=prefix[n]+measureRow(firstIndent,scene,start,options).advancePx;
    const solve=(a,k)=>{
      if(k===rows)return a===n?[]:null;if(a===n||n-a<rows-k)return null;
      const key=a+':'+k;if(memo.has(key))return memo.get(key);
      if(prefix[n]-prefix[a]>(rows-k)*scene.widthPx){memo.set(key,null);return null;}
      const indent=k===0?firstIndent:continuationIndent;
      const state=a===0?start:tokens[a-1].after;
      const indentWidth=measureRow(indent,scene,state,options).occupiedPx;
      const candidates=edges[a];let best=null;
      for(let j=candidates.length-1;j>=0;j--){const e=candidates[j];if(e.width+indentWidth>scene.widthPx)continue;
        const tail=solve(e.end,k+1);if(tail){
          const result=[[a,e.end,indent],...tail];
          if(!balanced){memo.set(key,result);return result;}
          result.cost=(tail.cost||0)+((e.width+indentWidth)*rows-totalAdvance)**2;
          if(best===null||result.cost<best.cost)best=result;
        }}
      memo.set(key,best);return best;
    };
    const selected=solve(0,0);if(selected)return selected.map(([a,b,indent])=>indent+tokens.slice(a,b).map(t=>t.text).join(''));
  }
  fail('overflow',`Text cannot fit ${exactRows??ceiling} rows within ${scene.widthPx}px`,{scene:scene.id,widthPx:scene.widthPx,maxRows:exactRows??ceiling});
}
function logical(text){return text.split('\n').map((line,i)=>i?line.replace(/^[　 ]+/, ''):line).join('');}
export function validate(text,sceneId,options={}) {
  const scene=effectiveScene(sceneId,options),result=measure(text,scene.id,options), issues=[];
  if(result.rows.length>(options.maxLines??scene.maxLines??Infinity))issues.push({code:'rows',message:'Too many physical rows'});
  result.rows.forEach((row,i)=>{
    if(row.occupiedPx>scene.widthPx)issues.push({code:'width',row:i+1,widthPx:row.occupiedPx,limitPx:scene.widthPx});
    if(scene.kind==='dialogue'&&i>0&&!/^　[^　 ]/.test(row.text))issues.push({code:'indent',row:i+1,message:'Expected one fullwidth continuation indent'});
    const v=visible(row.text).replace(/^[　 ]+/,'');
    if(v&&i>0&&contracts.forbiddenStart.includes(Array.from(v)[0]))issues.push({code:'punctuation_start',row:i+1});
    if(v&&i<result.rows.length-1&&contracts.forbiddenEnd.includes(Array.from(v).at(-1)))issues.push({code:'punctuation_end',row:i+1});
  });
  return {...result,valid:issues.length===0,issues};
}
function layoutFixed(text,sceneId,options={},targetWidth=null) {
  const scene=effectiveScene(sceneId,options), original=normalize(text);checkOptions(options,scene);
  if(targetWidth!==null)scene.widthPx=targetWidth;
  options={protectWords:scene.protectWords,...options};
  if(options.escapedNewlines)text=original.replace(/\\n/g,'\n');else text=original;
  rejectDynamic(text);
  if(!text.trim())fail('input','Text must not be empty');
  // Alignment cards and independent option rows are distinct owners, not prose.
  if(scene.kind==='dialogue'&&(/^[　 ]/.test(text)||/”\n[　 ]*“/.test(visible(text))))
    fail('owner_contract','Aligned cards and independent choices need an owner-specific contract');
  let lines;
  if(scene.kind==='dialogue'){
    const count=text.split('\n').length;
    const exact=options.preserveLineCount===true||(scene.id==='battle'&&options.preserveLineCount!==false)?count:null;
    lines=partition(logical(text),scene,options,'',scene.continuationIndent,exact,options.maxLines??scene.maxLines);
  }else{
    const blocks=[];
    for(const row of text.split('\n')){
      if(!row.trim()){blocks.push({blank:row||((scene.id.includes('scroll'))?'　':'')});continue;}
      const indent=/^[　 ]*/.exec(row)[0],body=row.slice(indent.length),last=blocks.at(-1);
      if(last&&last.body!==undefined&&!indent)last.body+=body;else blocks.push({indent,body});
    }
    lines=[];let state=initial(scene);
    for(const block of blocks){
      if(block.blank!==undefined){lines.push(block.blank);continue;}
      const part=partition(block.body,scene,{...options,initialState:state},block.indent,'',null,options.maxLines??null);
      lines.push(...part);for(const row of part)state=measureRow(row,scene,state,options).state;
    }
  }
  const physical=lines.join('\n');
  if(logical(physical)!==logical(text)&&scene.kind==='dialogue')fail('invariant','Layout changed authored content');
  const checked=validate(physical,scene.id,options);
  if(!checked.valid)fail('invariant','Generated layout failed validation',{issues:checked.issues});
  const output=options.escapedNewlines?physical.replace(/\n/g,'\\n'):physical;
  return {version,scene:scene.id,profile:scene.profileId,text:output,changed:output!==original,widthPx:scene.widthPx,step:scene.step,...checked,compiledText:expandCompact(physical,scene.id)};
}
// Paragraph tails and blank separators do not vote on the common line width.
// One pixel of tolerance covers native narrow glyph overhang, not added spacing.
function nonfinalWidths(result) {
  const rows=result.rows, widths=[];
  for(let i=0;i+1<rows.length;i++){
    if(rows[i].text.trim()&&rows[i+1].text.trim()&&!/^[　 ]/.test(rows[i+1].text))widths.push(rows[i].occupiedPx);
  }
  return widths;
}
function uniformity(result) {
  const widths=nonfinalWidths(result), spread=widths.length?Math.max(...widths)-Math.min(...widths):0;
  let aligned=0;
  for(const width of widths)aligned=Math.max(aligned,widths.filter(w=>w>=width&&w<=width+1).length);
  return {spreadPx:spread,excessSpreadPx:Math.max(0,spread-1),unalignedRows:widths.length-aligned,nonfinalWidthsPx:widths};
}
export function layout(text,sceneId,options={}) {
  const scene=effectiveScene(sceneId,options), baseline=layoutFixed(text,sceneId,options);
  if(scene.widthSelection!=='uniform_nonfinal'||(options.packing??scene.packing)!=='max_width')return baseline;
  let best=baseline,selected=scene.widthPx,score=uniformity(baseline),tested=1;
  const candidateOptions={...options,maxLines:options.maxLines??baseline.rows.length};
  // Descending order resolves equal consistency in favour of the widest layout.
  for(let width=scene.widthPx-1;score.excessSpreadPx>0&&width>=scene.step;width--){
    let candidate;
    try{candidate=layoutFixed(text,sceneId,candidateOptions,width);}
    catch(error){
      if(error.code==='overflow'||error.code==='invariant'&&error.details?.issues?.every(i=>i.code==='rows'))continue;
      throw error;
    }
    tested++;
    const next=uniformity(candidate);
    if(next.excessSpreadPx<score.excessSpreadPx||next.excessSpreadPx===score.excessSpreadPx&&next.unalignedRows<score.unalignedRows){
      best=candidate;selected=width;score=next;
    }
  }
  return {...best,widthPx:scene.widthPx,selectedWidthPx:selected,widthSelection:{policy:'uniform_nonfinal',testedWidths:tested,...score,withinTolerance:score.spreadPx<=1}};
}
export function dispatch(request){
  if(!request||typeof request!=='object')fail('input','Expected a JSON request');
  const action=request.action||'layout';if(!['layout','measure','validate','expand'].includes(action))fail('action','Unknown action');
  if(action==='expand')return {text:expandCompact(request.text,request.scene)};
  return {layout,measure,validate}[action](request.text,request.scene,request.options||{});
}
