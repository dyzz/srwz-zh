/** Pure SRWZ layout core. No DOM, filesystem, process, or font measurement APIs. */
import { contracts } from './contracts.mjs';
import {proportionalMetric,proportionalFontSha256,continuationIndentMetric} from './proportional-selection.mjs';
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
const tmTagRE = /＜[／/]?[ｔt][ｍm]＞|<\/?tm>/;
const tmScopeRE = /＜[ｔt][ｍm]＞[^＜＞\n]+＜[／/][ｔt][ｍm]＞|<tm>[^<>\n]+<\/tm>/y;
const tmScopesRE = new RegExp(tmScopeRE.source, 'g');
const nativeScopeRE = new RegExp('<width:[0-9A-Fa-f]{2}><space:[0-9A-Fa-f]{2}>(?:<height:[0-9A-Fa-f]{2}>)?' +
  '(?:[A-Za-z0-9Ａ-Ｚａ-ｚ０-９ .,:：．_\x27/／＋+％%~～〜×÷±＝=　－−·《》（）-]|<height:[0-9A-Fa-f]{2}>)+?' +
  '(?:<width:[0-9A-Fa-f]{2}><space:[0-9A-Fa-f]{2}>|<space:[0-9A-Fa-f]{2}><width:[0-9A-Fa-f]{2}>)(?:<height:[0-9A-Fa-f]{2}>)?', 'y');
const latinRE = /[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+(?:[.·_-][A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+)*[ 　]?/y;
const proportionalLatinRE = /[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+(?:[.·_\/-][A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+)*(?:[ 　][0-9０-９]+)?[ 　]?/y;
const numberRE = /(?:第[0-9０-９]+(?:话|章|关|幕|次|号|代|阶段|批)?|[0-9０-９]+(?:[.,][0-9０-９]+)*(?:%|％|岁|年|月|日|时|分钟|分|秒|米|公里|千米|海里|节|话|号|机|艘|人|倍|层|级|点|个)?)/y;
const rangeCacheKey=Symbol('request-local proportional row widths');
const splitIdentifierKey=Symbol('overwide identifier fallback');
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
  if(options.chinesePunctuation!==undefined&&!['native','compact'].includes(options.chinesePunctuation))fail('options','Unknown Chinese punctuation policy');
  if(options.typography!==undefined&&!['native','proportional'].includes(options.typography))fail('options','Unknown typography');
  if(options.continuationIndent!==undefined&&!['fullwidth','opener'].includes(options.continuationIndent))fail('options','Unknown continuation indent');
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
export function expandCompact(text, sceneId, options = {}) {
  const scene = sceneOf(sceneId); text = normalize(text);
  let out = '', i = 0;
  while (i < text.length) {
    if (text.startsWith('<z>', i)) {
      const m = match(scopeRE, text, i);
      if (!m) fail('compact_scope', 'Malformed, nested, or unsupported compact scope', { offset: i });
      out += options.typography==='proportional'?m[1]:scopeNative(m[1], scene); i += m[0].length;
    } else {
      if (text.startsWith('</z>', i)) fail('compact_scope', 'Unmatched compact closing tag', { offset: i });
      const ch = String.fromCodePoint(text.codePointAt(i)); out += ch; i += ch.length;
    }
  }
  return out;
}
function rejectDynamic(text, scene) {
  if (tmTagRE.test(text) && (scene?.id !== 'sp_story_map' || tmTagRE.test(text.replace(tmScopesRE, '')))
      || /^@[+-]?[0-9<]|\[[+-]?(?:[0-9]|<(?:color|width|height|space):)/.test(text))
    fail('owner_contract', 'Dynamic template, repeat, or square parameter needs an owner-specific contract');
}
function mapNumberTemplate(text, scene, offset) {
  return scene.id === 'sp_story_map' && (text[offset] === '＜' || text[offset] === '<')
    ? match(tmScopeRE, text, offset)?.[0] : undefined;
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
function measureRow(text, scene, start, options, collectGlyphs = true) {
  text = expandCompact(text, scene.id, options); rejectDynamic(text, scene);
  if (/[\r\n]/.test(text)) fail('input', 'Row measurement accepts one physical row');
  if (options.keywordLinks) keywordSpans(text);
  let state = { ...start }, x = 0, right = 0, i = 0; const glyphs = [];
  while (i < text.length) {
    const template = mapNumberTemplate(text, scene, i);
    if (template) {
      // Reserve the full native advance for the formatter’s eight digits, including fallback drawing.
      const advance = 8 * scene.step;
      if (collectGlyphs) glyphs.push({text:template, x, width:advance, height:state.height, advance, yOffset:0, baselineResidual16:0, placeholder:true});
      x += advance;
      right = Math.max(right, x);
      i += template.length;
      continue;
    }
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
      } else if (/^<[A-Za-z0-9]+:/.test(token) && !/^<(?:color|3[1-5]):[0-9A-Fa-f]{2}>$/.test(token)) {
        fail('control', `Unregistered native tag: ${token}`);
      } else {
        const cells = /^[%$]/.test(token) ? (options.placeholderCells ?? 6) : /^<[+-]?[0-9<]/.test(token) ? 1 : 0;
        if (cells) {
          if(collectGlyphs)glyphs.push({ text: token, x, width: (cells - 1) * state.step + state.width, height: state.height, advance: cells * state.step, placeholder: true });
          right = Math.max(right, x + (cells - 1) * state.step + state.width); x += cells * state.step;
        }
      }
      i += token.length; continue;
    }
    if ('@<{$%'.includes(text[i]) && (/^@?</.test(text.slice(i)) || /^\{[0-9A-Za-z]/.test(text.slice(i)) || /^\$[A-Za-z]/.test(text.slice(i)) || /^%[-+#0.*$0-9A-Za-z]/.test(text.slice(i))))
      fail('control', 'Unrecognized control syntax', { offset: i });
    const ch = String.fromCodePoint(text.codePointAt(i)); i += ch.length;
    if (options.keywordLinks && (ch === '《' || ch === '》')) continue;
    const metric=options.typography==='proportional'?proportionalMetric(text,i-ch.length,scene.id,options,state):null;
    const gx=x-(metric?.bearing||0),width=metric?.width??state.width,advance=metric?.advance??state.step;
    if(collectGlyphs)glyphs.push({text:ch,yOffset:metric?.yOffset??0,baselineResidual16:metric?.baselineResidual16??0,x:gx,width,height:metric?.height??state.height,advance,placeholder:false});
    // Bank Latin glyphs sit centred in a hanzi-wide cell: their ink ends with the advance.
    if (ch !== ' ' && ch !== '　') right = Math.max(right, metric?.advanceBox ? x + advance : gx + width);
    x += advance;
  }
  return { text, advancePx: x, occupiedPx: Math.max(x, right), glyphs, state };
}
function fitWidth(row, scene) {
  const last = row.glyphs.at(-1);
  if (!scene.trailingPunctuationPx || !last || !'，。、；：？！…”’）》】'.includes(last.text)) return row.occupiedPx;
  let bodyEdge = row.advancePx - last.advance;
  for (const glyph of row.glyphs.slice(0, -1)) {
    if (glyph.text !== ' ' && glyph.text !== '　') bodyEdge = Math.max(bodyEdge, glyph.x + glyph.width);
  }
  return Math.max(bodyEdge, row.occupiedPx - scene.trailingPunctuationPx);
}
export function measure(text, sceneId, options = {}) {
  const scene = effectiveScene(sceneId,options); checkOptions(options,scene); text = normalize(text);
  if (options.escapedNewlines) text = text.replace(/\\n/g, '\n');
  if(options.typography==='proportional')text=expandCompact(text,scene.id,options);
  let state = initial(scene);
  const indent = openerIndent(text, scene, options);
  const rows = text.split('\n').map((line, i) => {
    const r = measureRow(line, scene, state, options); state = r.state;
    const row = { text: line, advancePx: r.advancePx, occupiedPx: r.occupiedPx, glyphs: r.glyphs };
    // The stored indent of a continuation row is the blank glyph that advances
    // like the compact opening quote, so its text starts under the first row's.
    if (indent && i > 0 && /^　[^　 ]/.test(line) && row.glyphs[0]?.text === '　') {
      const delta = row.glyphs[0].advance - indent.advance;
      row.glyphs[0].advance = indent.advance;
      for (const glyph of row.glyphs.slice(1)) glyph.x -= delta;
      row.advancePx -= delta; row.occupiedPx -= delta;
    }
    if (scene.trailingPunctuationPx) row.fitPx = fitWidth(row, scene);
    return row;
  });
  return { scene: scene.id, rows, state, ...(options.typography==='proportional'?{fontSha256:proportionalFontSha256}:{}) };
}
// A dialogue line that opens with compact punctuation stores each continuation
// indent as the blank glyph of the same advance (tools/srwz/continuation_indent.py).
// Measurement, validation and the row solver all budget that advance, not a full cell.
function openerIndent(text, scene, options) {
  if (options.continuationIndent === 'fullwidth' || options.typography !== 'proportional' || options.chinesePunctuation !== 'compact' || scene.kind !== 'dialogue') return null;
  const indent = continuationIndentMetric(scene.id);
  return indent && indent.openers.includes(Array.from(visible(text))[0] ?? '') ? indent : null;
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
  rejectDynamic(text, scene); const terms = termsFor(scene, options.protectedTerms);
  const links = options.keywordLinks ? keywordSpans(text) : new Map();
  const controlled=controlledTerms(text,terms,options);
  const tokens=[]; let offset=0, state={...startState}, pending='', pendingBefore=null;
  while(offset<text.length) {
    let value='', atomic=false;
    const template=mapNumberTemplate(text,scene,offset);
    const scope=match(scopeRE,text,offset), native=match(nativeScopeRE,text,offset), control=match(controlRE,text,offset);
    if(template){value=template;atomic=true;}
    else if(controlled.has(offset)){value=controlled.get(offset);atomic=true;}
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
      // Latin identifiers remain intact even when Chinese word protection is off.
      if(options.typography==='proportional'&&!options[splitIdentifierKey]){
        const m=match(proportionalLatinRE,text,offset);if(m)candidates.push(m[0]);
      }
      if(text.startsWith('……',offset)||text.startsWith('——',offset)){candidates.push(text.slice(offset,offset+2));atomic=true;}
      candidates.sort((a,b)=>b.length-a.length||(a>b?-1:1));
      value=candidates[0]||String.fromCodePoint(text.codePointAt(offset));
    }
    const before=pendingBefore||{...state}; const extent=measureRow(value,scene,state,options,false);state=extent.state;offset+=value.length;
    if(!extent.advancePx){pendingBefore=before;pending+=value;continue;}
    const token={text:pending+value,advance:extent.advancePx,occupied:extent.occupiedPx,before,after:{...state},atomic,visible:template?'名':visible(value)};
    pending='';pendingBefore=null;
    if(token.occupied>scene.widthPx && !atomic && Array.from(value).length>1) {
      tokens.push(...tokensFor(value,scene,before,{...options,protectWords:false,[splitIdentifierKey]:true}));
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
  if((scene.kind==='prose'||scene.preserveAuthoredRows)&&(right===' '||right==='　'))return false;
  return !contracts.forbiddenEnd.includes(left||'\0')&&!contracts.forbiddenStart.includes(right||'\0');
}
function partition(text,scene,options,firstIndent='',continuationIndent='',exactRows=null,maxRows=scene.maxLines,authored=null) {
  const start=options.initialState||initial(scene), tokens=tokensFor(text,scene,start,options), n=tokens.length;
  if(!n)return [firstIndent];
  if(n>6000)fail('complexity','Too many layout tokens');
  const prefix=[0];for(const t of tokens)prefix.push(prefix.at(-1)+t.advance);
  const narrowIndent=authored?authored.narrowIndent:continuationIndent==='　'?openerIndent(firstIndent+text,scene,options):null;
  const measureRanges=options.typography==='proportional'||scene.trailingPunctuationPx;
  const cache=options[rangeCacheKey],cacheId=JSON.stringify([scene.id,tokens.map(t=>t.text),start]);
  if(cache&&!cache.has(cacheId))cache.set(cacheId,new Map());
  const widths=cache?.get(cacheId);
  const range=(a,b)=>{if(measureRanges){
    const key=a*(n+1)+b;
    if(widths?.has(key))return widths.get(key);
    const row=measureRow(tokens.slice(a,b).map(t=>t.text).join(''),scene,tokens[a].before,options,Boolean(scene.trailingPunctuationPx));
    const width=scene.trailingPunctuationPx?fitWidth(row,scene):row.occupiedPx;
    widths?.set(key,width);return width;
  }let edge=0;for(let i=a;i<b;i++)edge=Math.max(edge,prefix[i]-prefix[a]+tokens[i].occupied);return Math.max(prefix[b]-prefix[a],edge);};
  // A newly appended Latin character can narrow the preceding space. Allow
  // that edge to recover; 126 bounds one 63px advance plus cell overhang.
  // Legal edges are cached once and independent of row count.
  const edges=Array.from({length:n},()=>[]);
  for(let a=0;a<n;a++)for(let b=a+1;b<=n;b++){
    const w=range(a,b);if(w>scene.widthPx){if(measureRanges&&w<=scene.widthPx+126)continue;break;}if(legal(tokens,b,scene))edges[a].push({end:b,width:w});
  }
  // Exact lower bound from the legal-edge graph, ignoring indentation. This
  // remains safe when a row boundary changes contextual Latin spacing.
  const remainingRows=new Array(n+1).fill(Infinity);remainingRows[n]=0;
  for(let a=n-1;a>=0;a--)for(const e of edges[a])remainingRows[a]=Math.min(remainingRows[a],1+remainingRows[e.end]);
  const ceiling=Math.min(maxRows??n,n), minimum=exactRows??(measureRanges?Math.min(ceiling,remainingRows[0]):Math.max(1,Math.ceil(prefix[n]/scene.widthPx))), limit=exactRows??ceiling;
  if(!Number.isInteger(ceiling)||ceiling<1||!Number.isInteger(minimum)||minimum<1||limit>ceiling)fail('rows','Invalid physical row budget');
  for(let rows=minimum;rows<=limit;rows++){
    const memo=new Map();
    const balanced=(options.packing??scene.packing)==='balanced_width';
    const totalAdvance=(options.typography==='proportional'?measureRow(text,scene,start,options,false).advancePx:prefix[n])+measureRow(firstIndent,scene,start,options,false).advancePx;
    const solve=(a,k)=>{
      if(k===rows)return a===n?[]:null;if(a===n||n-a<rows-k||remainingRows[a]>rows-k)return null;
      const key=a+':'+k;if(memo.has(key))return memo.get(key);
      if(!measureRanges&&prefix[n]-prefix[a]>(rows-k)*scene.widthPx){memo.set(key,null);return null;}
      const indent=k===0?firstIndent:continuationIndent;
      const state=a===0?start:tokens[a-1].after;
      const compactIndent=k===0?authored?.firstIndent:narrowIndent;
      const indentWidth=compactIndent?compactIndent.advance:measureRow(indent,scene,state,options,false).occupiedPx;
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
function preserveRows(text,scene,options) {
  const {rows}=measure(text,scene.id,options), maxRows=options.maxLines??scene.maxLines;
  if(rows.length>maxRows)fail('rows','Authored rows exceed the map box',{scene:scene.id,maxRows});
  const narrowIndent=openerIndent(text,scene,options), lines=[];
  let state=initial(scene);
  for(const [i,row] of rows.entries()) {
    if(row.fitPx<=scene.widthPx)lines.push(row.text);
    else {
      const indent=/^[　 ]*/.exec(row.text)[0], body=row.text.slice(indent.length);
      const remaining=maxRows-lines.length-(rows.length-i-1);
      if(remaining<2||!body)fail('overflow','Authored row exceeds the map box',{scene:scene.id,row:i+1,widthPx:row.occupiedPx,maxRows});
      const firstIndent=i>0&&indent==='　'?narrowIndent:null;
      lines.push(...partition(body,scene,{...options,initialState:state},indent,scene.continuationIndent,null,remaining,{narrowIndent,firstIndent}));
    }
    state=measureRow(row.text,scene,state,options,false).state;
  }
  return lines;
}
// Battle subtitles clip at screen X=640. Measured per trailing glyph on Metal 4x, then 2px of margin.
// Validation only: automatic wrapping still packs to scene.widthPx.
const BATTLE_TRAILING_ALLOWANCE_PX={'？':20,'》':20,'：':21,'】':21,'”':22,'）':22,'。':23,'、':24,'，':26,'；':26,'！':27};
function battleTrailingHangs(row,scene,options){
  if(scene.id!=='battle'||options.typography!=='proportional')return false;
  const last=row.glyphs.filter(g=>g.text!==' '&&g.text!=='　').at(-1),allowance=last&&BATTLE_TRAILING_ALLOWANCE_PX[last.text];
  return allowance!==undefined&&row.advancePx<=scene.widthPx+allowance;
}
export function validate(text,sceneId,options={}) {
  const scene=effectiveScene(sceneId,options),result=measure(text,scene.id,options), issues=[];
  if(result.rows.length>(options.maxLines??scene.maxLines??Infinity))issues.push({code:'rows',message:'Too many physical rows'});
  result.rows.forEach((row,i)=>{
    if((row.fitPx??row.occupiedPx)>scene.widthPx&&!battleTrailingHangs(row,scene,options))issues.push({code:'width',row:i+1,widthPx:row.occupiedPx,limitPx:scene.widthPx});
    if(scene.preserveAuthoredRows)return;
    if(scene.kind==='dialogue'&&i>0&&!/^　[^　 ]/.test(row.text))issues.push({code:'indent',row:i+1,message:'Expected one fullwidth continuation indent'});
    const v=visible(row.text).replace(/^[　 ]+/,'');
    // An authored dialogue row may open with an ellipsis, as the Japanese rows do; automatic breaks still never put one there.
    if(v&&i>0&&contracts.forbiddenStart.includes(Array.from(v)[0])&&!(scene.kind==='dialogue'&&Array.from(v)[0]==='…'))issues.push({code:'punctuation_start',row:i+1});
    if(v&&i<result.rows.length-1&&contracts.forbiddenEnd.includes(Array.from(v).at(-1)))issues.push({code:'punctuation_end',row:i+1});
  });
  return {...result,valid:issues.length===0,issues};
}
function layoutFixed(text,sceneId,options={},targetWidth=null) {
  const scene=effectiveScene(sceneId,options), original=normalize(text);checkOptions(options,scene);
  if(targetWidth!==null)scene.widthPx=targetWidth;
  options={protectWords:scene.protectWords,...options};
  if(options.escapedNewlines)text=original.replace(/\\n/g,'\n');else text=original;
  rejectDynamic(text,scene);
  if(!text.trim())fail('input','Text must not be empty');
  // Alignment cards and independent option rows are distinct owners, not prose.
  if(scene.kind==='dialogue'&&!scene.preserveAuthoredRows&&(/^[　 ]/.test(text)||/”\n[　 ]*“/.test(visible(text))))
    fail('owner_contract','Aligned cards and independent choices need an owner-specific contract');
  let lines;
  if(scene.preserveAuthoredRows)lines=preserveRows(text,scene,options);
  else if(scene.kind==='dialogue'){
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
      lines.push(...part);for(const row of part)state=measureRow(row,scene,state,options,false).state;
    }
  }
  const physical=lines.join('\n');
  if(logical(physical)!==logical(text)&&scene.kind==='dialogue')fail('invariant','Layout changed authored content');
  const checked=validate(physical,scene.id,options);
  if(!checked.valid)fail('invariant','Generated layout failed validation',{issues:checked.issues});
  const output=options.escapedNewlines?physical.replace(/\n/g,'\\n'):physical;
  return {version,scene:scene.id,profile:scene.profileId,text:output,changed:output!==original,widthPx:scene.widthPx,step:scene.step,...checked,compiledText:expandCompact(physical,scene.id,options)};
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
      const width=options.typography==='proportional'?measureRow(tokens.slice(a,b+1).map(t=>t.text).join(''),scene,tokens[a].before,options,false).occupiedPx:Math.max(advance,occupied);if(width>scene.widthPx){if(options.typography==='proportional'&&width<=scene.widthPx+126)continue;break;}
      if(legal(tokens,b+1,scene)){edges[a].push({end:b+1,width});if(b+1<n)widths.add(width);}
    }
  }
  // Uniformity may give up at most one native cell of the panel width.
  // If an identifier makes that impossible, retain the full-width baseline.
  const floor=options.typography==='proportional'?scene.widthPx-scene.step:0;
  const values=[...widths].filter(w=>w>=floor).sort((a,b)=>a-b);
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
  const original=text;
  if(options?.typography==='proportional'){
    text=expandCompact(text,sceneId,options);
  }
  const result=layoutInternal(text,sceneId,options);
  return {...result,changed:result.text!==original};
}
function layoutInternal(text,sceneId,options={}) {
  // Width search revisits the same contextual rows hundreds of times. Cache
  // only within this request, so policy and corpus changes never reuse widths.
  if(options?.typography==='proportional')options={...options,[rangeCacheKey]:new Map()};
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
    if(options.typography==='proportional'&&next.nonfinalWidthsPx.some(w=>w<scene.widthPx-scene.step))return;
    if(next.excessSpreadPx<score.excessSpreadPx||next.excessSpreadPx===score.excessSpreadPx&&(next.unalignedRows<score.unalignedRows||next.unalignedRows===score.unalignedRows&&widest(next)>widest(score))){
      best=candidate;selected=width;score=next;
    }
  };
  const stored=validate(authored,scene.id,options);
  if(stored.valid&&stored.rows.length<=rowBudget){
    consider({...baseline,...stored,text:options.escapedNewlines?authored.replace(/\n/g,'\\n'):authored,compiledText:expandCompact(authored,scene.id,options),changed:authored!==normalize(text)},Math.max(0,...nonfinalWidths(stored)));
  }
  const solved=uniformParagraph(authored,scene,options,rowBudget);
  if(solved){
    consider({...baseline,...solved.result,text:options.escapedNewlines?solved.result.text.replace(/\n/g,'\\n'):solved.result.text,compiledText:expandCompact(solved.result.text,scene.id,options),changed:solved.result.text!==authored},solved.width);
    return {...best,selectedWidthPx:selected,widthSelection:{policy:'uniform_nonfinal',method:'legal_break_intervals',testedWidths:tested,...score,withinTolerance:score.spreadPx<=1}};
  }
  const candidateOptions={...options,maxLines:rowBudget};
  // Descending widths prefer the fullest equally uniform page. A stored zero-
  // spread candidate cannot stop the search before wider candidates are tried.
  for(let width=scene.widthPx-1;width>=(options.typography==='proportional'?scene.widthPx-scene.step:scene.step);width--){
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
  const originalFields=fields;
  const scene=effectiveScene(sceneId,options);checkOptions(options,scene);
  if(options.typography==='proportional'&&Array.isArray(fields))fields=fields.map(f=>({...f,text:typeof f?.text==='string'?expandCompact(f.text,sceneId,options):f?.text}));
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
  const tokens=tokensFor(text,scene,initial(scene),{protectWords:scene.protectWords,...options}),n=tokens.length;
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
      const width=options.typography==='proportional'?measureRow(tokens.slice(a,b+1).map(t=>t.text).join(''),scene,tokens[a].before,options,false).occupiedPx:Math.max(advance,occupied);if(width>scene.widthPx){if(options.typography==='proportional'&&width<=scene.widthPx+126)continue;break;}
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
  return {version,scene:scene.id,profile:scene.profileId,...checked,text:physical,fields:resultFields,changed:resultFields.some((f,i)=>f.text!==originalFields[i].text),widthPx:scene.widthPx,step:scene.step,selectedWidthPx:Math.max(...widths),compiledText:expandCompact(physical,scene.id,options),widthSelection:{policy:'uniform_nonfinal',method:'native_field_capacity',testedWidths:0,spreadPx:spread,excessSpreadPx:Math.max(0,spread-1),unalignedRows:widths.length-aligned,nonfinalWidthsPx:widths,withinTolerance:spread<=1}};
}
export function dispatch(request){
  if(!request||typeof request!=='object')fail('input','Expected a JSON request');
  const action=request.action||'layout';if(action==='layout_fields')return layoutFixedFields(request.fields,request.scene,request.options||{});
  if(!['layout','measure','validate','expand'].includes(action))fail('action','Unknown action');
  if(action==='expand')return {text:expandCompact(request.text,request.scene,request.options||{})};
  return {layout,measure,validate}[action](request.text,request.scene,request.options||{});
}
