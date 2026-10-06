import sys,json,re,collections,hashlib
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/srwz/text.py').is_file())
sys.path.insert(0,str(ROOT/'tools'))
from srwz.text import encode_text,decode_text,control_notation_tokens,RUNTIME_FORMAT_TOKEN
from special_disc.writeback.migrate_slps_text import encoding_tables
M=json.loads((ROOT/'manifests/editions/sp/current.json').read_text())
PROPOSAL=ROOT/M['workspace']/'work/build/special-disc/text-candidate/font/proposal.json'
T,_,O,R=encoding_tables(PROPOSAL)
TAG=re.compile(r"<([A-Za-z0-9_]+):([A-Fa-f0-9]{2})>")
RAW=re.compile(r"\{([A-Fa-f0-9]{2})\}")
PATTERNS={'angle_button':re.compile(r"<[+-]?[0-9]+>"),'brace_numeric':re.compile(r"\{[0-9]+(?:[.][0-9]+)*\}"),'format':RUNTIME_FORMAT_TOKEN,'dollar':re.compile(r"\$[cflnF]")}
def expand(text):
 out=[]; spans=[];i=0
 while i<len(text):
  m=TAG.match(text,i)
  if m:
   v=T.inverse_tags.get(m[1]);v=int(m[1],16) if v is None and re.fullmatch('[A-Fa-f0-9]{2}',m[1]) else v
   if v is not None:
    out += [chr(v),chr(int(m[2],16))];spans += [(i,m.end())]*2;i=m.end();continue
  m=RAW.match(text,i)
  if m:out.append(chr(int(m[1],16)));spans.append((i,m.end()));i=m.end();continue
  out.append(text[i]);spans.append((i,i+1));i+=1
 return ''.join(out),spans
def controls(text):
 exp,spans=expand(text)
 for kind,pat in PATTERNS.items():
  for m in pat.finditer(exp):
   a,b=spans[m.start()][0],spans[m.end()-1][1];notation=text[a:b]
   native=encode_text(notation,T);written=encode_text(notation,T,overrides=O)
   yield dict(kind=kind,raw=m[0],notation=notation,source_start=a,native_hex=native.hex(),written_hex=written.hex(),drift=native!=written,readback=decode_text(written+b'\0',0,R).text)
def walk(x,path=''):
 if isinstance(x,dict):
  for k,v in x.items():
   if isinstance(v,str) and (k in ('translation','source_text','translated_text') or ('by_offset' in path)):
    yield path+'/'+k,x.get('id'),k,v
   elif isinstance(v,(dict,list)):yield from walk(v,path+'/'+k)
 elif isinstance(x,list):
  for i,v in enumerate(x):yield from walk(v,path+'/'+str(i))
rows=[];files=0;fields=0
for p in sorted((ROOT/'corpus/zh').rglob('*.json')):
 try: data=json.loads(p.read_text())
 except Exception:continue
 files+=1
 for pointer,id,field,text in walk(data):
  fields+=1
  for c in controls(text):rows.append(dict(file=str(p.relative_to(ROOT)),pointer=pointer,id=id,field=field,**c))
sp_files={f'corpus/zh/special-disc/{s}.json' for s in ['system-text','frame-text','story-dialogue','challenge-dialogue','battle-lines']}
summary={}
for scope,rs in [('all_zh_corpus',rows),('sp_five_active_corpora',[r for r in rows if r['file'] in sp_files])]:
 rs=[r for r in rs if r['field'] in ('translation','translated_text') or 'by_offset' in r['pointer']]
 summary[scope]={'control_occurrences':len(rs),'drift_occurrences':sum(r['drift'] for r in rs),'families':{kind:dict(occurrences=len(q),drifts=sum(x['drift'] for x in q),patterns=dict(collections.Counter(x['raw'] for x in q))) for kind in PATTERNS for q in [[r for r in rs if r['kind']==kind]]}}
result={'schema_version':1,'scope_note':'corpus occurrences may repeat across source sets; not unique runtime events; drift means byte contract difference, not proven visible regression','proposal':{'path':str(PROPOSAL.relative_to(ROOT)),'sha256':hashlib.sha256(PROPOSAL.read_bytes()).hexdigest()},'files_scanned':files,'text_fields_scanned':fields,'summary':summary,'sp_rows':[r for r in rows if r['file'] in sp_files],'all_drift_rows':[r for r in rows if r['drift']]}
p=ROOT/'work/analysis/control-sequences-20261006/corpus-audit.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':files,'fields':fields,'summary':summary},ensure_ascii=False,indent=2))
print('SP EXAMPLES')
seen=set()
for r in result['sp_rows']:
 if r['field']=='translation' and r['raw'] not in seen:
  print(json.dumps(r,ensure_ascii=False));seen.add(r['raw'])
