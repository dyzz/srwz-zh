/** Tag-free candidate layout. Production engine remains separately selectable.
 * All widths come from the generated native-font registry; no browser fonts.
 */
import {measure as legacyMeasure, expandCompact, layout as constrainedLayout, layoutFixedFields as constrainedFields, LayoutError} from './engine.mjs';
import {proportionalMetric} from './proportional-selection.mjs';
import {contracts} from './contracts.mjs';
import {proportionalMetrics} from './proportional-metrics.mjs';

export function migrateCompact(text, scene) {
  // Validate nesting/character restrictions before removing obsolete markup.
  expandCompact(text, ['weapon','weapon_main'].includes(scene) ? 'main_flow' : scene);
  return text.replaceAll('<z>', '').replaceAll('</z>', '');
}
const blank = ch => ch === ' ' || ch === '　';
function glyphOffset(text, start, glyph) {
  const controls=new RegExp(contracts.controls,'y');
  for(let at=start;at<text.length;){
    controls.lastIndex=at;const control=controls.exec(text);
    if(control && control[0]!==glyph){at+=control[0].length;continue;}
    if(text.startsWith(glyph,at))return at;
    at+=String.fromCodePoint(text.codePointAt(at)).length;
  }
  throw new LayoutError('invariant','Measured glyph missing from source');
}
export function measure(text, scene, options = {}) {
  const clean = migrateCompact(text, scene);
  if(!['weapon','weapon_main'].includes(scene))return {...legacyMeasure(clean,scene,{...options,typography:'proportional'}),text:clean};
  // Weapon list native records: CJK 16x9, advance 16; Latin overridden below.
  // No wrap budget is inferred from this measurement-only panel contract.
  const prefix=scene==='weapon_main'?'<width:14><space:14><height:09>':'<width:10><space:10><height:09>';
  const base = legacyMeasure(prefix+clean, 'main_flow', options);
  if(prefix) base.rows[0].text=base.rows[0].text.slice(prefix.length);
  const rows = base.rows.map(row => {
    let pen = 0, right = 0, sourceOffset = 0;
    const glyphs = row.glyphs.map((glyph, i, source) => {
      const at=glyphOffset(row.text,sourceOffset,glyph.text);
      sourceOffset=at+glyph.text.length;
      const metric=glyph.placeholder?null:proportionalMetric(row.text,at,scene,options);
      const g = metric ? {...glyph, x:pen-metric.bearing, width:metric.width,
        height:metric.height, yOffset:metric.yOffset??0, baselineResidual16:metric.baselineResidual16??0, advance:metric.advance} : {...glyph, x:pen};
      if (!blank(g.text)) right = Math.max(right, g.x + g.width);
      pen += g.advance;
      return g;
    });
    return {...row, advancePx:pen, occupiedPx:Math.max(pen,right), glyphs};
  });
  return {...base, scene, rows, text:clean, fontSha256:proportionalMetrics.fontSha256};
}
export function center(text, scene, centerX = 0, options = {}) {
  if (!Number.isFinite(centerX)) throw new LayoutError('input','Invalid center coordinate');
  const result = measure(text, scene, options);
  // Matches the native signed -(advance/2), truncated toward zero.
  return {...result, rows:result.rows.map(row => {
    const originX = centerX - Math.trunc(row.advancePx/2);
    return {...row, originX, glyphs:row.glyphs.map(g=>({...g,x:g.x+originX}))};
  })};
}
export function layout(text, scene, options = {}) {
  return constrainedLayout(text,scene,{...options,typography:'proportional'});
}
export function layoutFixedFields(fields, scene, options = {}) {
  return constrainedFields(fields,scene,{...options,typography:'proportional'});
}
