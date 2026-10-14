"""Build a local bilingual listening-review document from the subtitle source."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]


def render(source, audio_dir, outdir, markdown):
    document = json.loads(source.read_text())
    captions = document['captions']
    editorial = document.get('editorial_review', {})
    sources = editorial.get('sources', {})
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'audio').mkdir(exist_ok=True)
    groups, payload = {}, []
    for caption in captions:
        row = dict(caption)
        row['editorial_sources'] = [sources[key] for key in row.get('editorial_source_refs', [])]
        groups.setdefault(row['scene_name'], []).append(row)
        wav = audio_dir / f"ccc-{row['ccc_id']:05d}-16k.wav"
        destination = outdir / 'audio' / wav.name
        if wav.resolve() != destination.resolve():
            shutil.copyfile(wav, destination)
        row['audio'] = 'data:audio/wav;base64,' + base64.b64encode(wav.read_bytes()).decode()
        payload.append(row)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    data = json.dumps({'source_sha256': digest,
                       'compatible_source_hashes': document.get('review_storage_compatible_source_hashes', []),
                       'editorial_review': editorial, 'captions': payload}, ensure_ascii=False).replace('</', '<\\/')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SP 事件演出字幕 · 逐句听校</title><style>
*{box-sizing:border-box}body{margin:0;color:#263344;background:#f3f5f8;font:16px/1.65 system-ui,sans-serif}header{padding:24px 32px;background:#192d43;color:white}h1{margin:0;font-size:26px}header p{margin:6px 0;color:#cad9e8}button{font:inherit;border:1px solid #b7c7d5;border-radius:7px;padding:7px 12px;cursor:pointer;background:white;color:#1d486a}main{max-width:1250px;margin:auto;display:grid;grid-template-columns:230px 1fr;gap:24px;padding:24px}nav{position:sticky;top:15px;height:max-content;display:grid;gap:7px}nav button{text-align:left}nav button.active{background:#1e5278;color:white}article{min-width:0}.card{background:white;border:1px solid #d8e0e8;border-radius:10px;padding:20px;margin:0 0 16px}.meta{font-size:13px;color:#65758a}.jp{font-size:18px}.zh{font-size:20px;padding:10px 12px;background:#f3f8fc;border-left:3px solid #4a829f;min-height:50px}.note{background:#fff3d9;padding:10px;border-radius:6px;color:#735222;font-size:14px}.terms{font-size:13px;color:#486b61}.raw{font-size:14px;color:#69788b}audio{display:block;width:100%;margin:12px 0}.toolbar{display:flex;gap:15px;align-items:center;flex-wrap:wrap;margin:15px 0}.check{display:block;margin-top:12px}details{margin-top:12px}code{font-size:12px;word-break:break-all}#progress{color:#557185}h2{margin-top:0}@media(max-width:750px){main{display:block;padding:15px}nav{position:static;margin-bottom:20px;grid-template-columns:1fr 1fr}header{padding:20px}.zh{font-size:19px}}@media print{header,nav,.toolbar,audio,button{display:none}main{display:block}.card{break-inside:avoid}}
</style><header><h1>SP 事件演出字幕 · 逐句听校</h1><p>12 段 / 37 句 · 已完成文字润色 · 仍待逐句原音听校</p><p>原音来自SP盘。对应动画资源与本篇一致，语音编号有所调整；巨神Σ的“充能”音频与本篇字节不同，本页采用SP版本。</p><p>本轮已统一放行口令、纠正超重合神并补充原作资料；CCC 368完整喊法与パイルダー译名仍待确认。第七版候选已采用本稿润色文本及新标题，字幕按4倍尺寸渲染后直接缩到原生帧缓冲所需尺寸；LRPS2记录见项目中的第七版验证文档。播放原音，对照日文和中文；勾选仅记录已听校，不会自动写回项目。</p></header>
<main><nav id="scenes"></nav><article><div class="toolbar"><button id="export">导出核对稿 JSON</button><label><input id="unreviewed" type="checkbox">只看未核对</label><label><input id="flagged" type="checkbox">只看有听校提示</label><span id="progress"></span></div><div id="content"></div></article></main>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),rows=data.captions,key='srwz-event-review-'+data.source_sha256;let saved={};try{let value=localStorage.getItem(key);if(value===null){for(const hash of data.compatible_source_hashes||[]){value=localStorage.getItem('srwz-event-review-'+hash);if(value!==null){localStorage.setItem(key,value);break}}}saved=JSON.parse(value||'{}')}catch{};let selected=rows[0].scene_name;
function persist(){try{localStorage.setItem(key,JSON.stringify(saved))}catch{}}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function render(){const nav=document.getElementById('scenes');nav.replaceChildren();for(const name of [...new Set(rows.map(r=>r.scene_name))]){const list=rows.filter(r=>r.scene_name===name),count=list.filter(r=>saved[r.id]?.checked).length,b=node('button',name+'  '+count+'/'+list.length,name===selected?'active':'');b.onclick=()=>{selected=name;render()};nav.append(b)}const target=document.getElementById('content');target.replaceChildren(node('h2',selected));for(const r of rows.filter(r=>r.scene_name===selected)){const s=saved[r.id]||{};if(document.getElementById('unreviewed').checked&&s.checked)continue;if(document.getElementById('flagged').checked&&!r.review_note)continue;const card=node('section',undefined,'card');card.append(node('div','Effect '+r.effect+' · CCC '+r.ccc_id+' · '+r.start_seconds.toFixed(2)+'–'+r.end_seconds.toFixed(2)+' 秒 · 帧 '+r.start_frame+'–'+r.end_frame,'meta'));const audio=node('audio');audio.controls=true;audio.preload='none';audio.src=r.audio;card.append(audio,node('div',r.japanese_candidate,'jp'));const zh=node('div',s.chinese??r.chinese_draft,'zh');zh.contentEditable='true';zh.setAttribute('aria-label','中文字幕草稿');zh.oninput=()=>{saved[r.id]={...saved[r.id],chinese:zh.textContent};persist()};card.append(zh);if(r.review_note)card.append(node('p',r.review_note,'note'));for(const ref of r.editorial_sources||[]){const p=node('p',undefined,'terms'),a=node('a',ref.title);a.href=ref.url;a.target='_blank';a.rel='noopener noreferrer';p.append(a,document.createTextNode('：'+ref.supports));card.append(p)}if(r.glossary_bindings.length)card.append(node('p','术语：'+r.glossary_bindings.map(b=>b.translation+'（'+b.id+' / '+b.status+'）').join('；'),'terms'));const details=node('details'),summary=node('summary','查看 Whisper 原始识别与来源');details.append(summary,node('p',r.japanese_whisper||'［独立片段未识别出文字］','raw'),node('code',r.id+' · ADPCM SHA256 '+r.audio_sha256));card.append(details);const label=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.checked=!!s.checked;check.onchange=()=>{saved[r.id]={...saved[r.id],checked:check.checked};persist();render()};label.append(check,document.createTextNode(' 我已对照原音核对本句'));card.append(label);target.append(card)}document.getElementById('progress').textContent='已核对 '+rows.filter(r=>saved[r.id]?.checked).length+' / '+rows.length}
document.getElementById('unreviewed').onchange=render;document.getElementById('flagged').onchange=render;document.getElementById('export').onclick=()=>{const result={source_sha256:data.source_sha256,editorial_review:data.editorial_review,captions:rows.map(({audio,...r})=>({...r,chinese_draft:saved[r.id]?.chinese??r.chinese_draft,review_status:saved[r.id]?.checked?'user_listening_reviewed':'awaiting_user_listening_review'}))};const u=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),a=node('a');a.href=u;a.download='sp-event-subtitles-reviewed.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};render();
</script></html>'''.replace('__DATA__', data)
    (outdir / 'review.html').write_text(html)
    lines = ['# SP 事件演出中文字幕听校稿（2026-10-13）', '',
             '12段共37句已完成本轮文字润色，仍待逐句人工听校。本文未修改现有全局术语表或剧情语料。', '',
             f'[打开逐句原音听校页面](issue-assets/{outdir.name}/review.html)。页面可播放原音、编辑中文、勾选核对状态并导出JSON；不会自动写回项目。', '',
             '本稿原音来自SP盘。对应动画资源与本篇一致，语音编号有所调整；巨神Σ的“充能”音频与本篇字节不同，采用SP版本。详见[两盘资源比较](SP_EVENT_RESOURCE_COMPARISON_20261013.md)。', '',
             '时间为相对于对应effect开始的原生60帧时间轴；地图前置动画和加载耗时不计入这个相对时间。字幕字号增至32，字外透明、白字黑描边阴影，画面范围由y384～416下移并加高至y388～428。', '',
             '本轮修订：出击口令统一为“准许起飞／准许弹射”；纠正“超重合神”；按原作技名候选采用“无限叱责掌”；统一行动口气、润色直译表达，并补充逐句查证来源。', '',
             '重点听校：瑟利安的人名、CCC 368完整喊法、パイルダー的中文称呼及叫喊拟声。万丈的否定语义已有官方文字支持，游戏具体读音仍待核对。CCC 368的“合神——超重斩”仅暂存旧候选，不可视为定稿。', '',
             '第七版候选采用本稿润色文本及用户指定的12个标题；字幕按4倍尺寸渲染后直接缩到原生帧缓冲所需纹理尺寸，字号32、底部位置和透明底保持不变。最新构建与LRPS2验证记录见[第七版字幕画质记录](SP_EVENT_SUBTITLE_QUALITY_V7_20261013.md)。文稿仍待人工听校，运行通过不代表译文已审核。', '']
    for name, group in groups.items():
        lines += [f'## {name}', '', '| 时间 / CCC | 日文整理候选 | 中文字幕草稿 |', '| --- | --- | --- |']
        for r in group:
            link = f"issue-assets/{outdir.name}/audio/ccc-{r['ccc_id']:05d}-16k.wav"
            lines.append(f"| [{r['start_seconds']:.2f}–{r['end_seconds']:.2f}s / {r['ccc_id']}]({link}) | {r['japanese_candidate'].replace('|','｜')} | {r['chinese_draft'].replace('|','｜')} |")
        for r in group:
            if r['glossary_bindings']:
                lines += ['', f"- CCC {r['ccc_id']} 术语：" + '；'.join(f"{b['id']} → {b['translation']}（{b['status']}）" for b in r['glossary_bindings'])]
            if r['review_note']:
                lines += ['', f"- CCC {r['ccc_id']} 听校提示：{r['review_note']}"]
            for source_item in r['editorial_sources']:
                lines += ['', f"- CCC {r['ccc_id']} 查证：[{source_item['title']}]({source_item['url']})。{source_item['supports']}"]
        lines += ['']
    lines += ['## 来源', '', f'字幕源：`config/products/special-disc/event-subtitles.json`，SHA-256 `{digest}`。', '',
              '原始Whisper输出与整理候选在JSON中分开保存；网页包含独立原音，便于离线听校。术语引用均带ID、当前译名和来源文件，未找到直接条目的口号已另行注明。', '']
    markdown.write_text('\n'.join(lines))
    shutil.copyfile(source, outdir / 'subtitle-draft.json')
    print(f'Wrote {len(captions)} caption review cards to {outdir / "review.html"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'config/products/special-disc/event-subtitles.json')
    parser.add_argument('--audio-dir', type=Path, required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    render(args.source, args.audio_dir, args.outdir, args.markdown)
