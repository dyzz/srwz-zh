from pathlib import Path
import json,hashlib
from PIL import Image
R=Path.cwd();source=R/'work/runtime/lrps2/library-optical-final-20261021/original';p=source/'lily-top.png';im=Image.open(p).convert('RGB')
rois={'digit_1':[96,218,105,245],'digit_4':[107,218,120,245],'age_chinese':[120,218,138,245],'body_G':[221,162,234,188],'body_chinese':[200,162,220,188]};rows=[]
for name,(left,top,right,bottom) in rois.items():
 for threshold in (100,120,140):
  pixels=[(x,y) for y in range(top,bottom) for x in range(left,right) if min(im.getpixel((x,y)))>threshold and max(im.getpixel((x,y)))-min(im.getpixel((x,y)))<30]
  xs,ys=zip(*pixels);rows.append(dict(label=name,roi=[left,top,right,bottom],threshold=threshold,bbox=[min(xs),min(ys),max(xs)+1,max(ys)+1],visible_height=max(ys)-min(ys)+1))
receipt=json.loads((source/'receipt.json').read_text());out=R/'docs/issue-assets/native-text-rendering-20261021'
(out/'optical-pixel-final.json').write_text(json.dumps(dict(scope='sampled LRPS2 bright-text ROI extents at three intensity thresholds; not whole-font optical proof',source_image=str(p.relative_to(R)),image_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),iso_sha256=receipt['iso_sha256'],measurements=rows,decision='final calibrated candidate: letter optical compensation retained; digits use native body height without Y shift'),indent=2)+'\n')
print(rows)
