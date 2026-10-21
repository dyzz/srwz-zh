"""Rebuild the source/corpus/control/patch snapshot; no production writes."""
from pathlib import Path
import sys,json,hashlib,collections,re
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.text import control_notation_tokens,load_text_table
from srwz.library import ZKAN_TEXT_TAGS,ZKAN_BINARY_TAGS
from srwz.library_typography import library_typography
from srwz.library_body_metrics import EDITIONS,trampoline
from srwz.library_optical_metrics import regions,layout
OUT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths=['tools/srwz/text.py','tools/srwz/renderer_metrics.py','tools/srwz/chinese_layout.py','tools/srwz/library.py','tools/srwz/library_typography.py','tools/srwz/library_body_metrics.py','tools/srwz/library_height_restore.py','tools/srwz/library_optical_metrics.py','tools/build_library_v02_component.py','tools/build_full_story_components.py','tools/srwz/best_build.py','tools/special_disc/writeback/shared_library.py','tools/special_disc/writeback/build_full_text.py','tools/special_disc/verification/verify_full_text.py','config/text-layout/zh-layout-profiles.json','vendor/upstream-python/project/tbl_all.json']
inputs=[dict(path=p,size=(R/p).stat().st_size,sha256=sha(R/p)) for p in paths]
counts=collections.Counter();examples={};corpus=[];errors=[];templates=collections.Counter();fields=0
def walk(node,pointer=''):
 if isinstance(node,dict):
  for k,v in node.items():
   ptr=pointer+'/'+str(k)
   if k in ('translation','source_text') and isinstance(v,str):yield ptr,v
   else:yield from walk(v,ptr)
 elif isinstance(node,list):
  for i,v in enumerate(node):yield from walk(v,pointer+'/'+str(i))
for p in sorted((R/'corpus/zh').rglob('*.json')):
 obj=json.loads(p.read_text());n=0
 for ptr,text in walk(obj):
  fields+=1;n+=1
  for name,pattern in [('tm_fullwidth',r'＜ｔｍ＞.*?＜／ｔｍ＞'),('tm_ascii',r'<tm>.*?</tm>'),('double_angle',r'<<[^>]+>>'),('literal_escape',r'\\[nrt]|\\u[0-9A-Fa-f]{4}'),('keyword_brackets',r'《[^》]+》')]:
   templates[name]+=len(re.findall(pattern,text,re.S))
  try:tokens=control_notation_tokens(text)
  except (ValueError,UnicodeError) as exc:
   errors.append(dict(path=str(p.relative_to(R)),pointer=ptr,error=str(exc)));continue
  for t in tokens:
   family=t.text
   if t.kind=='text_tag':family=re.sub(r':[0-9A-Fa-f]{2}>',':XX>',family)
   elif t.kind=='raw_byte':family='{XX}'
   elif t.kind=='runtime_format':family='printf-format'
   elif t.text.startswith('<'):family='numeric-angle-selector'
   elif t.text.startswith('{'):family='numeric-brace-parameter'
   key=(t.kind,family);counts[key]+=1
   rows=examples.setdefault(key,[])
   if len(rows)<3:rows.append(dict(path=str(p.relative_to(R)),pointer=ptr,token=t.text))
 if n:corpus.append(dict(path=str(p.relative_to(R)),sha256=sha(p),text_fields=n))
patches={}
for ed,s in EDITIONS.items():
 j=lambda op,va:op<<26|(va>>2&0x3ffffff)
 import struct
 body=[(s['hook'],struct.pack('<I',j(3,s['draw'])),struct.pack('<I',j(3,s['cave']))),(s['cave'],bytes(44),trampoline(ed))]
 rows=[dict(owner=owner,va=f'0x{va:X}',file_offset=f'0x{va-s["delta"]:X}',size=len(after),before_hex=before.hex(),after_hex=after.hex(),after_sha256=hashlib.sha256(after).hexdigest()) for owner,items in [('library_body_metrics',body),('library_optical_metrics',regions(ed))] for va,before,after in items]
 patches[ed]=dict(va_file_delta=f'0x{s["delta"]:X}',total_write_span_bytes=sum(x['size'] for x in rows),writes=rows)
base=json.loads((R/'config/text-layout/zh-layout-profiles.json').read_text())
examples_compiled={f'{domain}/{tag}/{text}':library_typography(text,tag,domain=domain) for domain,tag,text in [('character','DSC2','EFA所属G士兵14岁Geo圣剑'),('character','DSCR','中文RX-78F14 99.9%中文'),('robot','DSCR','中文RX-78F14中文'),('character','PRDC','超重神GRAVION'),('character','HEIT','18.0m')]}
batch=json.loads((R/'docs/issue-assets/native-text-rendering-20261021/smaller-body/production-build.json').read_text())
out=dict(scope='source snapshot plus corpus/zh translation and source_text string fields; duplicates and inactive corpora included; occurrence counts are not active-game-event counts; no new runtime validation',source_inputs=inputs,corpus_inputs=corpus,scanned_files=len(corpus),scanned_text_fields=fields,tokens=[dict(kind=k[0],family=k[1],count=v,examples=examples[k]) for k,v in sorted(counts.items())],other_structural_markers=dict(templates),tokenization_errors=errors,text_table_tags={f'{k:02X}':v for k,v in load_text_table(R/'vendor/upstream-python/project/tbl_all.json').tags.items()},library_text_tags=sorted(ZKAN_TEXT_TAGS),library_binary_tags=sorted(ZKAN_BINARY_TAGS),layout_profiles=base['profiles'],native_patch_ledger=patches,compiled_examples=examples_compiled,current_build=dict(input_digest=batch['input_digest'],outputs=[dict(edition=x['edition_id'],output=x['output']) for x in batch['results']]))
(OUT/'snapshot.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(files=len(corpus),fields=fields,token_families=len(counts),tokenization_errors=len(errors),tags=out['text_table_tags'],library_tags=out['library_text_tags'],compiled_examples=examples_compiled,patch_bytes={ed:x['total_write_span_bytes'] for ed,x in patches.items()}),ensure_ascii=False,indent=2))
