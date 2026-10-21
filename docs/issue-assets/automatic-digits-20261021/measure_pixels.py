"""Thresholded sampled black-ink bounds in the real LRPS2 flow screenshot.
A few ROIs do not establish a whole-font typographic baseline.
"""
from pathlib import Path
import json,hashlib
from PIL import Image
E=Path(__file__).parent;rows=[]
for phase,name in [('before','013-before.png'),('after','target-reopened.png')]:
 p=E/'flow/sp'/name;im=Image.open(p).convert('RGB')
 for label,roi in [('0',(113,222,125,245)),('1',(126,222,136,245)),('3',(138,222,148,245)),('特',(148,222,164,245)),('别',(164,222,180,245)),('小',(180,222,196,245))]:
  for t in (40,80,120):
   pts=[(x,y) for y in range(roi[1],roi[3]) for x in range(roi[0],roi[2]) if max(im.getpixel((x,y)))<t];assert pts
   xs,ys=zip(*pts);rows.append(dict(phase=phase,glyph=label,threshold=t,roi=roi,bbox=[min(xs),min(ys),max(xs)+1,max(ys)+1],visible_height=max(ys)-min(ys)+1,image_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
(E/'pixel-samples.json').write_text(json.dumps(dict(scope=__doc__,measurements=rows),ensure_ascii=False,indent=2)+'\n')
for row in rows:
 if row['threshold']==80:print(row['phase'],row['glyph'],row['bbox'],row['visible_height'])
