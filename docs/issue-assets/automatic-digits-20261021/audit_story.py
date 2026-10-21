"""Read-only authored dialogue/control audit; excludes IDs and metadata digits."""
from pathlib import Path
import sys,json,re,hashlib,collections,struct
R=Path.cwd();sys.path.insert(0,str(R/'tools'))
from srwz.text import CONTROL_NOTATION,normalize_original_fullwidth_ascii
OUT=R/'work/analysis/latin-height-rootcause-20261021'
paths=sorted((R/'corpus/zh/story-dialogue').glob('*.json'))+[R/'corpus/zh/story-system-dialogue.json',R/'corpus/zh/story-tickers.json',R/'corpus/zh/story-z-reports.json',R/'corpus/zh/special-disc/story-dialogue.json',R/'corpus/zh/special-disc/challenge-dialogue.json']
rows=[];files=[]
for p in paths:
 d=json.loads(p.read_text());entries=d.get('entries',[]);counts=collections.Counter()
 for row in entries:
  t=row.get('translation','')
  if not t:continue
  counts['translated']+=1;plain=normalize_original_fullwidth_ascii(CONTROL_NOTATION.sub('',t))
  counts['visible_latin_or_digits']+=bool(re.search('[A-Za-z0-9]',plain))
  counts['compact_width_space']+='<width:0E><space:0C>' in t
  counts['height_control']+=bool(re.search('<height:',t))
  counts['contains_visible_013']+='013' in plain
  if re.search('<height:',t) or '013' in plain:
   rows.append(dict(path=str(p.relative_to(R)),id=row['id'],translation=t))
 files.append(dict(path=str(p.relative_to(R)),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),counts=dict(counts)))
total=collections.Counter()
for f in files:total.update(f['counts'])
report=dict(scope=__doc__,files=files,total=dict(total),selected_entries=rows,limits=['Authored corpus only, not complete ISO/runtime coverage','Visible digits counted only after removing full native control notation','Story, system dialogue, tickers, reports and SP challenge surfaces retain separate runtime ownership'])
(OUT/'story-control-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('files',len(files),dict(total));print('height entries',[(r['path'],r['id']) for r in rows if '<height:' in r['translation']][:20])
