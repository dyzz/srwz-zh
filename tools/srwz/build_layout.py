"""Production layout bridge to the exact browser/Node scene engine.

Resource owners retain source binding, timing decisions, encoding and capacity.
Stored dialogue is validated, never silently rewrapped by a build.
"""
from __future__ import annotations
import hashlib
import math
import re
from pathlib import Path
from .js_layout import ROOT, layout_batch, request_layout, JsLayoutError
from .typography_policy import options as typography_options, candidate_enabled

LIBRARY_SCENES={'CHAR':'library_character','ROBO':'library_robot','KYWD':'library_glossary'}
RUNTIME_FILES=('engine.mjs','contracts.mjs','cli.mjs','cli-handler.mjs','proportional-selection.mjs','proportional-metrics.mjs')

def runtime_inputs(root:Path=ROOT):
    return {f'shared_js_{Path(name).stem.replace("-","_")}':dict(path='shared/text-layout/'+name,
        sha256=hashlib.sha256((root/'shared/text-layout'/name).read_bytes()).hexdigest(),size=(root/'shared/text-layout'/name).stat().st_size)for name in RUNTIME_FILES}

def library_input(text):
    from .library_typography import normalize_body_controls
    # The shared prose engine distinguishes physical wraps from indented
    # paragraph starts and blank separators. Do not erase that ownership here.
    text=normalize_body_controls(text).replace('\r','')
    baseline='<width:15><space:15>'
    if re.search(r'<(?:width|space):',text) and not text.startswith(baseline):text=baseline+text
    return text

def library_batch(keys, *, typography=None, chinese_punctuation=None):
    typography,chinese_punctuation=typography_options(typography,chinese_punctuation)
    keys=list(keys);result={}
    batch_size=64 if typography=='proportional' else 256
    for start in range(0,len(keys),batch_size):
        group=keys[start:start+batch_size]
        from .library_typography import library_typography
        requests=[]
        for kind,text in group:
            prepared=library_input(text)
            if typography=='proportional':
                prepared=library_typography(prepared,'DSCR',domain={'CHAR':'character','ROBO':'robot','KYWD':'glossary'}[kind],typography=typography)
            requests.append(dict(scene=LIBRARY_SCENES[kind],text=prepared,options=dict(typography=typography,chinesePunctuation=chinese_punctuation)))
        for key,request,response in zip(group,requests,layout_batch(requests,timeout=120 if typography=='proportional' else 30)):
            if not response['ok']:
                result[key]=(False,response['error']['message']);continue
            value=response['result']
            expected=request['text']
            if typography=='proportional':expected=expected.replace('<z>','').replace('</z>','')
            if value['text'].replace('\n','')!=expected.replace('\n',''):raise ValueError('JS library layout changed authored content')
            result[key]=(True,(value['text'],tuple(math.ceil(r['occupiedPx']/value['step'])for r in value['rows'])))
    return result

def reflow_story(text,*,profile,protected_terms=(),stage_keyword_links=False,**_):
    from .chinese_layout import ChineseLayoutError,ReflowResult
    if (profile.profile_id,profile.default_advance_px,profile.maximum_width,profile.first_line_maximum_width,profile.continuation_indent)!=('story_dialogue',21,22,23,'　'):
        raise ChineseLayoutError('Shared JS story scene/profile drift')
    try:r=request_layout(text,'story',options=dict(maxLines=profile.maximum_lines,protectedTerms=list(protected_terms),keywordLinks=stage_keyword_links,typography=typography_options()[0],chinesePunctuation=typography_options()[1]))
    except JsLayoutError as error:raise ChineseLayoutError(str(error))from error
    return ReflowResult(text,r['text'],'shared_js',tuple(math.ceil(row['occupiedPx']/21)-(1 if i else 0)for i,row in enumerate(r['rows'])))

def reflow_prose(text,*,scene,maximum_lines=None,resource_id=None,typography=None,chinese_punctuation=None):
    typography,chinese_punctuation=typography_options(typography,chinese_punctuation)
    options={"typography":typography,"chinesePunctuation":chinese_punctuation}
    if maximum_lines is not None:options['maxLines']=maximum_lines
    if resource_id is not None:options['resourceId']=resource_id
    return request_layout(text,scene,options=options)

def stored_geometry_issues(rows,scene,*,batch_size=256,typography=None,chinese_punctuation=None):
    """Rows are (identity, text, keyword_links); reject geometry without reflow.

    Special aligned/choice owners keep their source structure. This gate checks
    physical widths/row count; existing owner gates still check their indents.
    """
    typography,chinese_punctuation=typography_options(typography,chinese_punctuation)
    rows=list(rows);issues={}
    for start in range(0,len(rows),batch_size):
        group=rows[start:start+batch_size]
        requests=[dict(action='measure',scene=scene,text=text.replace('\\n','\n'),options=dict(keywordLinks=links,typography=typography,chinesePunctuation=chinese_punctuation))for _,text,links in group]
        for (identity,_,_),response in zip(group,layout_batch(requests)):
            if not response['ok']:
                issues[identity]=(f'JS {response["error"]["message"]}',)
                continue
            measured=response['result'];limit=462 if scene=='battle'else 483;maximum=2 if scene=='battle'else 3
            if len(measured['rows'])>maximum or any(r['occupiedPx']>limit and not (scene=='battle' and battle_trailing_hangs(r,limit)) for r in measured['rows']):
                issues[identity]=(f'shared JS {scene} geometry exceeds {maximum} rows / {limit}px',)
    return issues

# Battle subtitles clip at screen X=640. Measured per trailing glyph on Metal 4x, then 2px of margin.
BATTLE_TRAILING_ALLOWANCE_PX = {'？':20,'》':20,'：':21,'】':21,'”':22,'）':22,'。':23,'、':24,'，':26,'；':26,'！':27}

def battle_trailing_hangs(row,limit):
    glyphs=[g for g in row['glyphs'] if g['text'] not in (' ','　')]
    allowance=BATTLE_TRAILING_ALLOWANCE_PX.get(glyphs[-1]['text']) if glyphs else None
    return allowance is not None and row['advancePx']<=limit+allowance

def verify_stored(rows,scene,*,batch_size=256,typography=None,chinese_punctuation=None):
    rows=list(rows)
    issues=stored_geometry_issues(rows,scene,batch_size=batch_size,
        typography=typography,chinese_punctuation=chinese_punctuation)
    if issues:
        identity=next(iter(issues))
        raise ValueError(f'{identity}: {"; ".join(issues[identity])}')
    return len(rows)

PROSE_HANGING_PX = 12
PROSE_HANGING_PUNCTUATION = frozenset('，。、；：？！')


def prose_row_width(row, hanging_px):
    """Count the full body and discount only eligible final punctuation."""
    glyphs = row['glyphs']
    occupied = row['occupiedPx']
    if not hanging_px or not glyphs or glyphs[-1]['text'] not in PROSE_HANGING_PUNCTUATION:
        return occupied
    body_edge = max((glyph['x'] + glyph['width'] for glyph in glyphs[:-1]
                     if glyph['text'] not in (' ', '　')), default=0)
    body_advance = row['advancePx'] - glyphs[-1]['advance']
    return max(body_edge, body_advance, occupied - hanging_px)


def prose_widths(rows, scene, *, hanging_px=0):
    """Measure and validate stored prose with its native scene and row budget."""
    typography, punctuation = typography_options()
    rows = list(rows)
    widths_by_id = {}
    for start in range(0, len(rows), 256):
        group = rows[start:start + 256]
        options = [dict(resourceId=identity, typography=typography, chinesePunctuation=punctuation)
                   for identity, _, _ in group]
        limits = layout_batch([dict(scene=scene, text='中', options=opts) for opts in options])
        measurements = layout_batch([
            dict(action='measure', scene=scene, text=text, options=opts)
            for (_, text, _), opts in zip(group, options, strict=True)
        ])
        for (identity, _, max_rows), limit, response in zip(group, limits, measurements, strict=True):
            if not limit['ok'] or not response['ok']:
                raise ValueError(f'{identity}: unsupported JS prose contract')
            width = limit['result']['widthPx']
            widths = tuple(prose_row_width(row, hanging_px) for row in response['result']['rows'])
            if max(widths, default=0) > width or (max_rows is not None and len(widths) > max_rows):
                raise ValueError(f'{identity}: shared JS prose geometry exceeds {width}px / {max_rows} rows')
            widths_by_id[identity] = widths
    return widths_by_id


def verify_prose(rows, scene, *, hanging_px=0):
    return len(prose_widths(rows, scene, hanging_px=hanging_px))


def fit_story(text,*,profile,protected_terms=(),stage_keyword_links=False,**kwargs):
    from .chinese_layout import dialogue_layout_issues,ReflowResult,dialogue_line_widths,fit_chinese_dialogue_layout
    if candidate_enabled():
        structured=text.startswith((' ','　')) or bool(re.search(r'”\n[　 ]*“',text))
        r=request_layout(text,'story',action='measure' if structured else 'layout',options=dict(typography='proportional',chinesePunctuation='compact',keywordLinks=stage_keyword_links,maxLines=profile.maximum_lines))
        final=r.get('compiledText') if not structured else '\n'.join(row['text'] for row in r['rows'])
        verify_stored([('candidate-dialogue',final,stage_keyword_links)],'story')
        return ReflowResult(text,final,'shared_js_proportional',tuple(math.ceil(row['occupiedPx']/21) for row in r['rows']))
    if not dialogue_layout_issues(text,profile=profile,stage_keyword_links=stage_keyword_links):
        return ReflowResult(text,text,'already_final',dialogue_line_widths(text,default_advance_px=profile.default_advance_px,stage_keyword_links=stage_keyword_links))
    # These are source-structured owners; the ordinary JS paragraph must reject them.
    if text.startswith((' ','　'))or re.search(r'”\n[　 ]*“',text):
        return fit_chinese_dialogue_layout(text,profile=profile,protected_terms=protected_terms,stage_keyword_links=stage_keyword_links,**kwargs)
    return reflow_story(text,profile=profile,protected_terms=protected_terms,stage_keyword_links=stage_keyword_links)

def fit_candidate_stories(texts,*,profile):
    """Batch candidate dialogue; structured owners keep their authored rows."""
    if not candidate_enabled():raise ValueError('Candidate dialogue policy is not enabled')
    texts=list(texts);result=[]
    for start in range(0,len(texts),128):
        group=texts[start:start+128];requests=[]
        for text in group:
            structured=text.startswith((' ','　')) or bool(re.search(r'”\n[　 ]*“',text))
            requests.append(dict(text=text,scene='story',action='measure' if structured else 'layout',options=dict(typography='proportional',chinesePunctuation='compact',maxLines=profile.maximum_lines)))
        for request,response in zip(requests,layout_batch(requests)):
            if not response['ok']:raise JsLayoutError(response['error'])
            r=response['result'];result.append(r['compiledText'] if request['action']=='layout' else '\n'.join(row['text'] for row in r['rows']))
    verify_stored([(str(i),text,False)for i,text in enumerate(result)],'story')
    return result

def check_runtime(root:Path=ROOT):
    """All edition entry points require the shared engine before build I/O."""
    import json,os,shutil,subprocess
    node=os.environ.get('SRWZ_NODE')or shutil.which('node')
    if not node:raise RuntimeError('Node.js required for production shared JS layout')
    scenes=('story','battle','main_flow','sp_flow','main_scroll','sp_scroll','main_scroll_strip','library_character','library_robot','library_glossary')
    requests=[dict(scene=scene,text='目标<z>MS-013</z>已锁定。',options=dict(preserveLineCount=False))for scene in scenes]
    raw=subprocess.run([node,str(root/'shared/text-layout/cli.mjs')],input=json.dumps(requests,ensure_ascii=False)+'\n',text=True,capture_output=True,check=True,timeout=30)
    responses=json.loads(raw.stdout)
    if len(responses)!=len(scenes)or any(not r['ok']or not r['result']['valid']for r in responses):raise RuntimeError('Shared JS production scene self-check failed')
    return dict(scenes=len(scenes),engine_version=responses[0]['result']['version'],inputs=runtime_inputs(root))
