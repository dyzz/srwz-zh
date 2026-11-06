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
function legal(tokens,end,scene) {
  if(end===tokens.length)return true;
  const left=Array.from(tokens[end-1].visible).at(-1), right=Array.from(tokens[end].visible)[0];
  // A generated prose continuation must not turn an internal separator into
  // an authored paragraph indent on the next formatting pass.
  if(scene?.kind==='prose'&&(right===' '||right==='　'))return false;
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
    const w=range(a,b);if(w>scene.widthPx)break;if(legal(tokens,b,scene))edges[a].push({end:b,width:w});
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
    if(options.preserveLineCount===true&&blocks.filter(block=>block.body!==undefined).length!==1)
      fail('owner_contract','Exact prose rows require one paragraph owned by the same display group');
    lines=[];let state=initial(scene);
    for(const block of blocks){
      if(block.blank!==undefined){lines.push(block.blank);continue;}
      const exact=options.preserveLineCount===true?text.split('\n').length:null;
      const part=partition(block.body,scene,{...options,initialState:state},block.indent,'',exact,options.maxLines??null);
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
// Solve a complete unindented paragraph, so moving one legal break can avoid
// a punctuation shortfall several rows later. Tails may be shorter; native
// advances, scope boundaries and the physical row budget stay unchanged.
function uniformParagraph(text,scene,options,maxRows) {
  if(options.preserveLineCount===true)return null;
  if(/^[　 ]|\n[　 ]|\n\n|\n$/.test(text))return null;
  const tokens=tokensFor(text.replaceAll('\n',''),scene,initial(scene),{protectWords:false,...options}),n=tokens.length;
  if(!n||n>6000)return null;
  const edges=Array.from({length:n},()=>[]),widths=new Set();
  for(let a=0;a<n;a++){
    let advance=0,occupied=0;
    for(let b=a;b<n;b++){
      occupied=Math.max(occupied,advance+tokens[b].occupied);advance+=tokens[b].advance;
      const width=Math.max(advance,occupied);if(width>scene.widthPx)break;
      if(legal(tokens,b+1,scene)){edges[a].push({end:b+1,width});if(b+1<n)widths.add(width);}
    }
  }
  const values=[...widths].sort((a,b)=>a-b);
  const path=(lo,hi)=>{
    const count=new Int32Array(n+1).fill(maxRows+1),previous=new Int32Array(n+1).fill(-1);count[0]=0;
    for(let a=0;a<n;a++)if(count[a]<maxRows){
      for(let i=edges[a].length-1;i>=0;i--){const e=edges[a][i];
        if(e.width>hi||e.end<n&&e.width<lo||count[a]+1>=count[e.end])continue;
        count[e.end]=count[a]+1;previous[e.end]=a;
      }
    }
    if(previous[n]<0)return null;
    const result=[];for(let b=n;b>0;){const a=previous[b];result.unshift(tokens.slice(a,b).map(t=>t.text).join(''));b=a;}
    return result;
  };
  let low=0,high=0,best=null;
  while(low<values.length&&high<values.length){
    if(high<low)high=low;
    const rows=path(values[low],values[high]);
    if(!rows){high++;continue;}
    const physical=rows.join('\n'),checked=validate(physical,scene.id,options);
    if(checked.valid){
      const result={...checked,text:physical},score=uniformity(result),width=Math.max(0,...score.nonfinalWidthsPx);
      if(!best||score.excessSpreadPx<best.score.excessSpreadPx||score.excessSpreadPx===best.score.excessSpreadPx&&(score.unalignedRows<best.score.unalignedRows||score.unalignedRows===best.score.unalignedRows&&width>best.width))best={result,score,width};
    }
    low++;
  }
  return best;
}
export function layout(text,sceneId,options={}) {
  const scene=effectiveScene(sceneId,options), baseline=layoutFixed(text,sceneId,options);
  if(scene.widthSelection!=='uniform_nonfinal'||(options.packing??scene.packing)!=='max_width')return baseline;
  let best=baseline,selected=scene.widthPx,score=uniformity(baseline),tested=1;
  if(score.excessSpreadPx===0)return {...baseline,selectedWidthPx:selected,widthSelection:{policy:'uniform_nonfinal',testedWidths:tested,...score,withinTolerance:true}};
  const authored=options.escapedNewlines?normalize(text).replace(/\\n/g,'\n'):normalize(text);
  // Existing legal rows are part of the owner's budget. Never discard a more
  // uniform reviewed layout merely because maximum-width fill uses fewer rows.
  const rowBudget=Math.min(options.maxLines??Infinity,Math.max(authored.split('\n').length,baseline.rows.length+(scene.widthSelectionExtraLines??0)));
  const widest=s=>Math.max(0,...s.nonfinalWidthsPx);
  const consider=(candidate,width)=>{
    const next=uniformity(candidate);
    if(next.excessSpreadPx<score.excessSpreadPx||next.excessSpreadPx===score.excessSpreadPx&&(next.unalignedRows<score.unalignedRows||next.unalignedRows===score.unalignedRows&&widest(next)>widest(score))){
      best=candidate;selected=width;score=next;
    }
  };
  const stored=validate(authored,scene.id,options);
  if(stored.valid&&stored.rows.length<=rowBudget){
    consider({...baseline,...stored,text:options.escapedNewlines?authored.replace(/\n/g,'\\n'):authored,compiledText:expandCompact(authored,scene.id),changed:authored!==normalize(text)},Math.max(0,...nonfinalWidths(stored)));
  }
  const solved=uniformParagraph(authored,scene,options,rowBudget);
  if(solved){
    consider({...baseline,...solved.result,text:options.escapedNewlines?solved.result.text.replace(/\n/g,'\\n'):solved.result.text,compiledText:expandCompact(solved.result.text,scene.id),changed:solved.result.text!==authored},solved.width);
    return {...best,selectedWidthPx:selected,widthSelection:{policy:'uniform_nonfinal',method:'legal_break_intervals',testedWidths:tested,...score,withinTolerance:score.spreadPx<=1}};
  }
  const candidateOptions={...options,maxLines:rowBudget};
  // Descending widths prefer the fullest equally uniform page. A stored zero-
  // spread candidate cannot stop the search before wider candidates are tried.
  for(let width=scene.widthPx-1;width>=scene.step;width--){
    if(score.excessSpreadPx===0&&width<widest(score))break;
    let candidate;
    try{candidate=layoutFixed(text,sceneId,candidateOptions,width);}
    catch(error){
      if(error.code==='overflow'||error.code==='invariant'&&error.details?.issues?.every(i=>i.code==='rows'))continue;
      throw error;
    }
    tested++;consider(candidate,width);
  }
  return {...best,widthPx:scene.widthPx,selectedWidthPx:selected,widthSelection:{policy:'uniform_nonfinal',testedWidths:tested,...score,withinTolerance:score.spreadPx<=1}};
}
// A native display group owns its fixed fields independently. Storage budgets
// are supplied by the encoder, never inferred from glyph widths or UTF-8.
export function layoutFixedFields(fields,sceneId,options={}) {
  const scene=effectiveScene(sceneId,options);checkOptions(options,scene);
  if(scene.kind!=='prose'||!Array.isArray(fields)||fields.length<1||fields.length>3)
    fail('owner_contract','Fixed prose groups require one to three native fields');
  for(const f of fields)if(!f||typeof f.text!=='string'||/[\r\n]/.test(f.text)||!Number.isInteger(f.capacityBytes)||f.capacityBytes<1||![0,1].includes(f.terminatorBytes))
    fail('field_capacity','Invalid native field or terminator budget');
  if(fields.slice(1).some(f=>/^[　 ]/.test(f.text)))fail('owner_contract','Separate paragraphs require separate native display groups');
  const text=normalize(fields.map(f=>f.text).join(''));
  rejectDynamic(text);
  if(new RegExp(contracts.controls,'g').test(text)||/<\/?z>/.test(text))
    fail('owner_contract','Fixed-field solver requires plain text with explicit encoded character byte lengths');
  const byteMap=options.encodedCharacterBytes;
  if(!byteMap||typeof byteMap!=='object')fail('field_capacity','Encoder character byte lengths are required');
  const tokens=tokensFor(text,scene,initial(scene),{protectWords:false}),n=tokens.length;
  if(n>400)fail('complexity','Fixed display group exceeds 400 layout tokens');
  const bytes=[0];
  for(const t of tokens){
    let size=0;for(const ch of t.text){const b=Object.hasOwn(byteMap,ch)?byteMap[ch]:null;
      if(!Number.isInteger(b)||b<1||b>8)fail('field_capacity','Missing encoder byte length',{character:ch});size+=b;}
    bytes.push(bytes.at(-1)+size);
  }
  const edges=Array.from({length:n},()=>[]);
  for(let a=0;a<n;a++){
    let advance=0,occupied=0;
    for(let b=a;b<n;b++){
      occupied=Math.max(occupied,advance+tokens[b].occupied);advance+=tokens[b].advance;
      const width=Math.max(advance,occupied);if(width>scene.widthPx)break;
      if(legal(tokens,b+1,scene))edges[a].push({end:b+1,width,bytes:bytes[b+1]-bytes[a]});
    }
  }
  let best=null;
  const better=(a,b)=>{for(let i=0;i<a.length;i++){if(a[i]!==b[i])return a[i]<b[i];}return false;};
  const search=(a,k,path)=>{
    if(k===fields.length){
      if(a!==n)return;
      const widths=path.map(p=>p.width),voters=widths.length>1?widths.slice(0,-1):widths;
      const spread=Math.max(...voters)-Math.min(...voters);
      const score=[spread,-Math.min(...voters),Math.max(...widths)-Math.min(...widths),...widths.map(w=>-w)];
      if(!best||better(score,best.score))best={path,score};return;
    }
    if(a===n)return;
    for(const edge of edges[a]){
      if(edge.bytes+fields[k].terminatorBytes>fields[k].capacityBytes||n-edge.end<fields.length-k-1)continue;
      search(edge.end,k+1,[...path,{...edge,start:a}]);
    }
  };
  search(0,0,[]);
  if(!best)fail('field_capacity','No legal layout fits the native field capacities');
  const resultFields=best.path.map((p,i)=>({...fields[i],text:tokens.slice(p.start,p.end).map(t=>t.text).join(''),encodedBytes:p.bytes+fields[i].terminatorBytes}));
  const physical=resultFields.map(f=>f.text).join('\n'),checked=validate(physical,scene.id,options);
  if(!checked.valid)fail('invariant','Fixed-field layout failed native geometry validation',{issues:checked.issues});
  const voters=checked.rows.length>1?checked.rows.slice(0,-1):checked.rows, widths=voters.map(r=>r.occupiedPx),spread=Math.max(...widths)-Math.min(...widths);
  const aligned=Math.max(...widths.map(w=>widths.filter(v=>v>=w&&v<=w+1).length));
  return {version,scene:scene.id,profile:scene.profileId,...checked,text:physical,fields:resultFields,changed:resultFields.some((f,i)=>f.text!==fields[i].text),widthPx:scene.widthPx,step:scene.step,selectedWidthPx:Math.max(...widths),compiledText:expandCompact(physical,scene.id),widthSelection:{policy:'uniform_nonfinal',method:'native_field_capacity',testedWidths:0,spreadPx:spread,excessSpreadPx:Math.max(0,spread-1),unalignedRows:widths.length-aligned,nonfinalWidthsPx:widths,withinTolerance:spread<=1}};
}
export function dispatch(request){
  if(!request||typeof request!=='object')fail('input','Expected a JSON request');
  const action=request.action||'layout';if(action==='layout_fields')return layoutFixedFields(request.fields,request.scene,request.options||{});
  if(!['layout','measure','validate','expand'].includes(action))fail('action','Unknown action');
  if(action==='expand')return {text:expandCompact(request.text,request.scene)};
  return {layout,measure,validate}[action](request.text,request.scene,request.options||{});
}
