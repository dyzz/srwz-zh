export type SceneId = 'story' | 'battle' | 'main_flow' | 'sp_flow' | 'main_scroll' | 'sp_scroll' | 'main_scroll_strip' | 'library_character' | 'library_robot' | 'library_glossary';
export interface LayoutOptions {
  preserveLineCount?: boolean;
  escapedNewlines?: boolean;
  protectWords?: boolean;
  keywordLinks?: boolean;
  maxLines?: number;
  placeholderCells?: number;
  protectedTerms?: string[];
  packing?: 'max_width' | 'balanced_width';
  resourceId?: string;
}
export interface Glyph { text:string;x:number;width:number;height:number;advance:number;placeholder:boolean }
export interface Row { text:string;advancePx:number;occupiedPx:number;glyphs:Glyph[] }
export interface FontState { width:number;height:number;step:number }
export interface Issue { code:string;row?:number;widthPx?:number;limitPx?:number;message?:string }
export interface Measured { scene:SceneId;rows:Row[];state:FontState }
export interface Validated extends Measured { valid:boolean;issues:Issue[] }
export interface LayoutResult extends Validated { version:string;profile:string;text:string;changed:boolean;widthPx:number;step:number;compiledText:string }
export interface Scene { id:SceneId;profileId:string;kind:'dialogue'|'prose';width:number;height:number;step:number;lineStep:number;columns:number;widthPx:number;maxLines:number|null;continuationIndent:string;compact:Record<string,number>;protectedTerms:string[];protectWords:boolean;packing:'max_width'|'balanced_width' }
export class LayoutError extends Error {code:string;details:Record<string,unknown>}
export const version:string;
export const sceneIds:readonly SceneId[];
export function getScene(id:SceneId):Scene;
export function expandCompact(text:string,scene:SceneId):string;
export function measure(text:string,scene:SceneId,options?:LayoutOptions):Measured;
export function validate(text:string,scene:SceneId,options?:LayoutOptions):Validated;
export function layout(text:string,scene:SceneId,options?:LayoutOptions):LayoutResult;
export function dispatch(request:{action?:'layout'|'measure'|'validate'|'expand';text:string;scene:SceneId;options?:LayoutOptions}):LayoutResult|Measured|Validated|{text:string};
