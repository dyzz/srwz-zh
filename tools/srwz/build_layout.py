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

LIBRARY_SCENES={'CHAR':'library_character','ROBO':'library_robot','KYWD':'library_glossary'}
RUNTIME_FILES=('engine.mjs','contracts.mjs','cli.mjs','cli-handler.mjs')

def runtime_inputs(root:Path=ROOT):
    return {f'shared_js_{Path(name).stem.replace("-","_")}':dict(path='shared/text-layout/'+name,
        sha256=hashlib.sha256((root/'shared/text-layout'/name).read_bytes()).hexdigest(),size=(root/'shared/text-layout'/name).stat().st_size)for name in RUNTIME_FILES}

def library_input(text):
    from .library_typography import normalize_body_controls
    text=normalize_body_controls(text).replace('\r','').replace('\n','')
    baseline='<width:15><space:15>'
    if re.search(r'<(?:width|space):',text) and not text.startswith(baseline):text=baseline+text
    return text

def library_batch(keys):
    keys=list(keys);result={}
    for start in range(0,len(keys),256):
        group=keys[start:start+256]
        requests=[dict(scene=LIBRARY_SCENES[kind],text=library_input(text))for kind,text in group]
        for key,request,response in zip(group,requests,layout_batch(requests)):
            if not response['ok']:
                result[key]=(False,response['error']['message']);continue
            value=response['result']
            if value['text'].replace('\n','')!=request['text']:raise ValueError('JS library layout changed authored content')
            result[key]=(True,(value['text'],tuple(math.ceil(r['occupiedPx']/value['step'])for r in value['rows'])))
    return result

def reflow_story(text,*,profile,protected_terms=(),stage_keyword_links=False,**_):
    from .chinese_layout import ChineseLayoutError,ReflowResult
    if (profile.profile_id,profile.default_advance_px,profile.maximum_width,profile.first_line_maximum_width,profile.continuation_indent)!=('story_dialogue',21,22,23,'　'):
        raise ChineseLayoutError('Shared JS story scene/profile drift')
    try:r=request_layout(text,'story',options=dict(maxLines=profile.maximum_lines,protectedTerms=list(protected_terms),keywordLinks=stage_keyword_links))
    except JsLayoutError as error:raise ChineseLayoutError(str(error))from error
    return ReflowResult(text,r['text'],'shared_js',tuple(math.ceil(row['occupiedPx']/21)-(1 if i else 0)for i,row in enumerate(r['rows'])))

def reflow_prose(text,*,scene,maximum_lines=None,resource_id=None):
    options={}
    if maximum_lines is not None:options['maxLines']=maximum_lines
    if resource_id is not None:options['resourceId']=resource_id
    return request_layout(text,scene,options=options)

def verify_stored(rows,scene,*,batch_size=256):
    """Rows are (identity, text, keyword_links); reject geometry without reflow.

    Special aligned/choice owners keep their source structure. This gate checks
    physical widths/row count; existing owner gates still check their indents.
    """
    rows=list(rows);count=0
    for start in range(0,len(rows),batch_size):
        group=rows[start:start+batch_size]
        requests=[dict(action='measure',scene=scene,text=text.replace('\\n','\n'),options=dict(keywordLinks=links))for _,text,links in group]
        for (identity,_,_),response in zip(group,layout_batch(requests)):
            if not response['ok']:raise ValueError(f'{identity}: JS {response["error"]["message"]}')
            measured=response['result'];limit=462 if scene=='battle'else 483;maximum=2 if scene=='battle'else 3
            if len(measured['rows'])>maximum or any(r['occupiedPx']>limit for r in measured['rows']):
                raise ValueError(f'{identity}: shared JS {scene} geometry exceeds {maximum} rows / {limit}px')
            count+=1
    return count

def verify_prose(rows,scene):
    """Validate stored prose with the same scene/resource contract, without reflow."""
    rows=list(rows)
    for start in range(0,len(rows),256):
        group=rows[start:start+256]
        probes=[dict(scene=scene,text='中',options=dict(resourceId=identity))for identity,_,_ in group]
        limits=layout_batch(probes)
        requests=[dict(action='measure',scene=scene,text=text,options=dict(resourceId=identity))for identity,text,_ in group]
        for (identity,_,max_rows),limit,response in zip(group,limits,layout_batch(requests)):
            if not limit['ok']or not response['ok']:raise ValueError(f'{identity}: unsupported JS prose contract')
            values=response['result']['rows'];width=limit['result']['widthPx']
            if any(row['occupiedPx']>width for row in values)or(max_rows is not None and len(values)>max_rows):
                raise ValueError(f'{identity}: shared JS prose geometry exceeds {width}px / {max_rows} rows')
    return len(rows)

def fit_story(text,*,profile,protected_terms=(),stage_keyword_links=False,**kwargs):
    from .chinese_layout import dialogue_layout_issues,ReflowResult,dialogue_line_widths,fit_chinese_dialogue_layout
    if not dialogue_layout_issues(text,profile=profile,stage_keyword_links=stage_keyword_links):
        return ReflowResult(text,text,'already_final',dialogue_line_widths(text,default_advance_px=profile.default_advance_px,stage_keyword_links=stage_keyword_links))
    # These are source-structured owners; the ordinary JS paragraph must reject them.
    if text.startswith((' ','　'))or re.search(r'”\n[　 ]*“',text):
        return fit_chinese_dialogue_layout(text,profile=profile,protected_terms=protected_terms,stage_keyword_links=stage_keyword_links,**kwargs)
    return reflow_story(text,profile=profile,protected_terms=protected_terms,stage_keyword_links=stage_keyword_links)

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
