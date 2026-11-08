"""Compare actual ARMSX2 glyph records with shared authoring metrics."""
import json,struct,sys,subprocess,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools'))
from srwz.armsx2_text_probe import load_codebook,decode_code
OUT=ROOT/'work/runtime/armsx2/keyword-list-20261108';book=load_codebook()
texts=['Side 3','Evidence 01','LOGOS','PLANT评议会议长']
js="import {measure} from './shared/text-layout/proportional.mjs'; console.log(JSON.stringify(JSON.parse(process.argv[1]).map(t=>measure(t,'keyword_list').rows[0])))"
expected=json.loads(subprocess.check_output(['/opt/homebrew/bin/node','--input-type=module','-e',js,json.dumps(texts)],cwd=ROOT,text=True))
results=[]
for edition in ['best','sp']:
 for page in [1,2]:
  p=OUT/edition/f'list-after-page{page}.jsonl'
  if not p.exists():p=OUT/edition/'list-after.jsonl'
  rows=[json.loads(l) for l in p.read_text().splitlines()]
  for frame in sorted({r['frame']for r in rows}):
   glyphs=[]
   for r in rows:
    if r['frame']!=frame:continue
    m=r['mem'];code=int.from_bytes(bytes.fromhex(m['@70000060:2']),'little');record=bytes.fromhex(m['s0:32'])
    glyphs.append(dict(text=unicodedata.normalize('NFKC',decode_code(code,book)),xy=struct.unpack_from('<hh',record,4),wh=struct.unpack_from('<hh',record,12),code=code))
   text=''.join(g['text']for g in glyphs)
   for target,want in zip(texts,expected):
    if target not in text:continue
    i=text.index(target);actual=glyphs[i:i+len(target)]
    assert ''.join(g['text']for g in actual)==target
    origin_x=actual[0]['xy'][0]-want['glyphs'][0]['x'];origin_y=actual[0]['xy'][1]-want['glyphs'][0].get('yOffset',0)
    for got,g in zip(actual,want['glyphs']):
     assert got['xy']==(origin_x+g['x'],origin_y+g.get('yOffset',0)),(edition,target,got,g)
     assert got['wh']==(g['width'],g['height']),(edition,target,got,g)
     if g['text']==' ':assert got['code']==0x8140
    results.append(dict(edition=edition,page=page,frame=frame,text=target,advance=want['advancePx'],glyphs=len(actual)))
 for t in texts:assert any(r['edition']==edition and r['text']==t for r in results),(edition,t)
(OUT/'draw-verification.json').write_text(json.dumps(dict(evidence='ARMSX2 actual glyph records versus shared JS',results=results),indent=2,ensure_ascii=False)+'\n')
print(len(results),'term occurrences match X/Y/width/height; fullwidth word spaces preserved')
