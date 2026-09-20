"""Import a user-reviewed SP export, verifying immutable source fields first.

The ZIP is data only. This command merges authored corpus text; it does not
patch an ISO. Unbound native fields are retained as explicit writeback targets.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.text import normalize_original_fullwidth_ascii

BASE=ROOT/'work/review/special-disc/sp-only-non-stage-text-20260919'
AREA=ROOT/'work/authoring/special-disc/review-imports/20260919-gpt6-pro'
LEDGER=ROOT/'corpus/zh/special-disc/reviewed-non-stage-text.json'
NATIVE=ROOT/'corpus/zh/special-disc/native-text.json'
OVERRIDES={
 'sd/flow/key/17ED0':('：切换至Special Disc','用户此前要求去掉“流程”；沿用已验证的按钮宽度。'),
 'sd/flow/key/17F00':('：切换至SRW Z','用户此前要求去掉“流程”；沿用已验证的按钮宽度。'),
}

def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(p.read_text())
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def norm(s):return normalize_original_fullwidth_ascii(s).replace('　',' ')
def need(ok,msg):
 if not ok:raise ValueError(msg)
def tokens(s):return re.findall(r'<[^>\n]+>|\{(?:[0-9A-Fa-f]{2}|n:03d)\}|%[-+0-9.]*[sdiu]',s)

def run(archive,apply):
 manifest=load(BASE/'manifest.json');baseline={};incoming={};statuses={};inputs={};metadata_changes=[]
 with zipfile.ZipFile(archive)as z:
  infos=z.infolist();need(sum(f.file_size for f in infos)<64*1024*1024,'review ZIP unexpectedly large');need(len({f.filename for f in infos})==len(infos),'duplicate ZIP names')
  for f in infos:
   p=PurePosixPath(f.filename);need(not p.is_absolute() and '..'not in p.parts and p.parts[0]==BASE.name,'unsafe archive path');need((f.external_attr>>16)&0o170000!=0o120000,'ZIP symlink rejected')
  for c in manifest['categories']:
   path=c['json'];original=load(BASE/path);review=json.loads(z.read(BASE.name+'/'+path))
   need({k:v for k,v in original.items()if k!='entries'}=={k:v for k,v in review.items()if k!='entries'},f'category metadata changed: {path}')
   old={r['id']:r for r in original['entries']};need(len(old)==len(review['entries']),'entry count changed')
   for row in review['entries']:
    id_=row['id'];need(id_ in old and id_ not in incoming,'unknown or repeated review ID')
    frozen=lambda r:{k:v for k,v in r.items()if k not in ['review_translation','review_notes']}
    need(frozen(row)==frozen(old[id_]),f'immutable fields changed: {id_}')
    need(sha(row['source_text'].encode())==row['source_text_sha256'],f'source hash mismatch: {id_}')
    need(isinstance(row['review_translation'],str)and isinstance(row['review_notes'],str),'invalid review values')
    baseline[id_]=old[id_];incoming[id_]=row
  statusdoc=json.loads(z.read(BASE.name+'/校订报告/逐条审阅状态.json'))
  statuses={r['id']:r for r in statusdoc['entries']};need(set(statuses)==set(incoming),'status index ID drift')
  need(len(incoming)==2282,'expected source inventory changed')
  corpus_paths=sorted({r['corpus_path'] for r in incoming.values()if r.get('corpus_path')})
  documents={p:load(ROOT/p)for p in corpus_paths};by_key={(p,r['id']):r for p,d in documents.items()for r in d['entries']}
  by_hash=collections.defaultdict(list)
  for (p,id_),r in by_key.items():by_hash[r['source_text_sha256']].append((p,id_))
  ledger=[];plans={};native=[];exceptions=[];empty=[];actual_changed=[]
  for id_,r in incoming.items():
   proposed=r['review_translation'];old=baseline[id_];effective=OVERRIDES.get(id_,(proposed,''))[0]
   if proposed and proposed!=(r['translation']or r['current_text']):actual_changed.append(id_)
   row=dict(id=id_,source_text=r['source_text'],source_text_sha256=r['source_text_sha256'],category=r['category'],submitted_translation=proposed,translation=effective,review_notes=r['review_notes'],locations=r['locations'],review_status=statuses[id_]['review_status'],terminology_check=statuses[id_]['terminology_or_context_check'],source_package_sha256=sha(archive.read_bytes()))
   if id_ in OVERRIDES:
    row['exception']=OVERRIDES[id_][1];exceptions.append(dict(id=id_,submitted=proposed,accepted=effective,reason=row['exception']))
   if not proposed:
    row.update(disposition='source_confirmation_pending',translation='');empty.append(id_);ledger.append(row);continue
   before=r['translation']or r['current_text']
   need(tokens(proposed)==tokens(before),f'control or template tokens changed: {id_}')
   need(proposed.count('\\n')==before.count('\\n'),f'battle escaped newline count changed: {id_}')
   need('\ufffd'not in proposed and '\0'not in proposed,f'invalid review text: {id_}')
   key=None
   if r.get('corpus_path'):key=(r['corpus_path'],r['corpus_id'])
   else:
    options=[k for k in by_hash[r['source_text_sha256']]if k[0].endswith('/frame-text.json')and by_key[k].get('category')in ['episode-title','synopsis']]
    if len(options)==1:key=options[0]
   if key:
    target=by_key[key];need(target['source_text_sha256']==r['source_text_sha256'],'corpus source drift')
    need(norm(target['translation'])==norm(r['translation']or r['current_text'])or not r.get('corpus_path'),f'corpus edited after export: {id_}')
    if key in plans:need(norm(plans[key]['translation'])==norm(effective),f'conflicting alias reviews: {id_}, {plans[key]["ids"]}')
    else:plans[key]=dict(translation=effective,ids=[],notes=[],terminology_check=False)
    plans[key]['ids'].append(id_);plans[key]['notes'].append(r['review_notes']);plans[key]['terminology_check']|=row['terminology_check']
    row.update(disposition='existing_corpus',corpus_path=key[0],corpus_id=key[1]);ledger.append(row)
   elif id_ in OVERRIDES or id_.startswith('sd/flow/key/'):
    row.update(disposition='existing_chart_key_help',config='config/editorial/special-disc/chart-key-help.json');ledger.append(row)
   elif norm(effective)==norm(r['current_text']):
    row['disposition']='retained_current_native_text';ledger.append(row)
   else:
    row.update(disposition='new_native_corpus',corpus_path=str(NATIVE.relative_to(ROOT)),corpus_id=id_);ledger.append(row)
    native.append(dict(id=id_,source_text=r['source_text'],source_text_sha256=r['source_text_sha256'],translation=effective,editorial_status='reviewed',review_author='GPT6 Pro; user-supplied',review_notes=r['review_notes'],terminology_check=row['terminology_check'],category=r['category'],locations=r['locations'],export_current_text=r['current_text'],origin='user-review:20260919-gpt6-pro',writeback_status='binding_and_layout_pending'))
  need(len(actual_changed)==527 and len(empty)==7,'submitted review accounting differs from independently calculated values')
  changes=[]
  for (path,id_),plan in plans.items():
   target=by_key[(path,id_)];changed=target['translation']!=plan['translation']
   if changed:changes.append(dict(path=path,id=id_,before=target['translation'],after=plan['translation'],review_ids=plan['ids']))
   target.update(translation=plan['translation'],editorial_status='reviewed',review_author='GPT6 Pro; user-supplied',review_origin='user-review:20260919-gpt6-pro',review_notes=list(dict.fromkeys(plan['notes'])),review_terminology_check=plan['terminology_check'])
  for path,d in documents.items():
   inputs[path]=sha((ROOT/path).read_bytes())
  counts=dict(export_entries=len(incoming),submitted_nonempty=len(incoming)-len(empty),submitted_actual_changes=len(actual_changed),submitted_retained=sum(r['review_status']=='retained'for r in ledger),pending_source=len(empty),accepted_entries=len(ledger)-len(empty),exceptions=len(exceptions),existing_corpus_unique_entries=len(plans),existing_corpus_text_changes=len(changes),new_native_entries=len(native),dispositions=dict(collections.Counter(r['disposition']for r in ledger)))
  report=dict(status='merged_editorial_only'if apply else 'validated_plan',package=dict(path=str(archive),sha256=sha(archive.read_bytes())),baseline_export=dict(path=str(BASE.relative_to(ROOT)),manifest_sha256=sha((BASE/'manifest.json').read_bytes()),iso=manifest['iso']),counts=counts,exceptions=exceptions,pending_source=empty,corpus_before=inputs,changes=changes,native_targets=[r['id']for r in native],iso_modified=False,notes='Source IDs, hashes and all non-review fields verified against local export. Existing and new native text is editorial acceptance, not runtime proof.')
  if apply:
   need(not LEDGER.exists()and not NATIVE.exists(),'review corpus already exists; do not overwrite a prior merge')
   AREA.mkdir(parents=True,exist_ok=True);shutil.copyfile(archive,AREA/'submitted.zip')
   for f in infos:
    if f.is_dir():continue
    dest=AREA/'submitted'/PurePosixPath(f.filename);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(f))
   for path,d in documents.items():
    backup=AREA/'before'/path;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/path,backup);write(ROOT/path,d)
   write(LEDGER,dict(schema_version=1,description='User-approved SP non-stage review ledger; not itself an ISO writeback component',review_origin='20260919-gpt6-pro',entries=ledger))
   write(NATIVE,dict(schema_version=1,description='Accepted native SP fields not covered by earlier corpus writers',source_iso=manifest['iso'],entry_count=len(native),entries=native))
   report['corpus_after']={path:sha((ROOT/path).read_bytes())for path in documents};write(AREA/'import-report.json',report)
  else:AREA.mkdir(parents=True,exist_ok=True);write(AREA/'import-plan.json',report)
  print(json.dumps(counts,ensure_ascii=False,indent=2))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args();run(a.archive.resolve(),a.apply)
if __name__=='__main__':main()
