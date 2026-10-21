from pathlib import Path
import json,shutil,hashlib
from PIL import Image,ImageDraw
R=Path.cwd();E=R/'docs/issue-assets/native-text-rendering-20261021';V=E/'vertical-refinement'
canvas=Image.new('RGB',(720,350),(20,20,20));draw=ImageDraw.Draw(canvas)
for i,(label,source) in enumerate((('Before: height14, Y-1',E/'optical-final/original/character'),('After: height13, Y-1',V/'final/original'))):
 draw.text((5,i*175+3),label,fill='white')
 for j,(page,left) in enumerate((('alex-top',125),('lily-top',175))):
  crop=Image.open(source/(page+'.png')).crop((left,160,left+175,235)).resize((350,150),Image.Resampling.NEAREST)
  canvas.paste(crop,(j*360,i*175+22))
canvas.save(V/'before-after.png')
for name in ('verify_vertical_runtime.py','record_vertical_result.py'):shutil.copy2(R/'work/analysis/library-font-fix-20261021'/name,V/name)
d=json.loads((E/'coverage.json').read_text());d['next_actions']=['Keep the broad native-text reverse-engineering goal open; the current practical font issue has a selected height13/Y-1 character-body candidate with matching LRPS2 results on Original, Best and SP.','Broader font/surface acceptance, lowercase descenders, mixed identifiers and robot pages remain separate coverage; do not generalize the two-character result to every glyph.'];d['completion_audit']['runtime_optical_candidate_accepted']='height13 Y-1 refinement: Lily and Alex top/scroll, all three current built ISOs; sampled EFA/G/Geo and digits; broader surfaces remain open';(E/'coverage.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
