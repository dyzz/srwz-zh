/** Context selection shared by measurement and all constrained layout paths. */
import {proportionalMetrics} from './proportional-metrics.mjs';
export const proportionalFontSha256=proportionalMetrics.fontSha256;
const key=ch=>{
 const c=ch||'', n=c.charCodeAt(0);
 // ASCII and unified Han are already NFKC-stable.
 return n<128||(n>=0x4e00&&n<=0x9fff)?c:c.normalize('NFKC');
};
const alnum=ch=>/^[A-Za-z0-9]$/.test(key(ch));
export function proportionalMetric(text,at,scene,options={},state=null){
 const profile=proportionalMetrics.profiles[scene];
 if(!profile)throw new Error(`Missing proportional profile: ${scene}`);
 const ch=String.fromCodePoint(text.codePointAt(at));
 const cjk=options.chinesePunctuation==='compact'?profile.cjkPunctuation?.[ch]:null;
 if(cjk&&(!state||(state.width===cjk.width&&state.step===cjk.width)))return {...cjk,height:state?.height??cjk.height};
 const normalized=key(ch);
 const direct=profile.glyphs[normalized];if(direct)return direct;
 const punctuation=profile.punctuation[normalized];
 const context=text.slice(Math.max(0,at-4),at+5);
 // The fast path covers the game's stable-width alphabet. Preserve the
 // established normalization behavior for other compatibility characters.
 const stable=/^[\x00-\x7f\u3000\u4e00-\u9fff\uff01-\uff5e]*$/.test(context);
 if(stable&&normalized!==' '&&!punctuation)return null;
 if(options.spacedSlash!==false&&(!stable||normalized===' '||normalized==='/')){
  const window=context.normalize('NFKC');
  const local=at-Math.max(0,at-4);
  for(const m of window.matchAll(/(?=([A-Za-z0-9] ?\/ ?[A-Za-z0-9]))/g)){
   if(local>m.index&&local<m.index+m[1].length-1)
    return normalized===' '?profile.space:profile.punctuation['/'];
  }
 }
 if(!alnum(text[at-1])||!alnum(text[at+ch.length]))return null;
 return ch===' '||ch==='　'?profile.space:punctuation||null;
}
