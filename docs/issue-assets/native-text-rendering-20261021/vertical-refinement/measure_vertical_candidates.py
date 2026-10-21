from pathlib import Path
import json
from PIL import Image,ImageDraw
R=Path.cwd();root=R/'work/runtime/lrps2/vertical-candidates-20261021'
sources={'h14-y1':R/'docs/issue-assets/native-text-rendering-20261021/optical-final/original/character'}
sources.update({p.name:p/'original' for p in root.iterdir() if p.is_dir() and (p/'original/alex-top.png').exists()})
rois={'alex-top':{'chinese':[113,162,135,189],'EFA':[137,162,171,189],'G':[214,162,226,189]},'lily-top':{'chinese':[200,162,220,189],'G':[221,162,234,189],'Geo':[221,190,255,217],'geo_chinese':[257,190,275,217],'digits':[96,218,120,245],'age':[120,218,138,245]}}
rows=[]
for name,source in sources.items():
 for page,rs in rois.items():
  im=Image.open(source/(page+'.png')).convert('RGB')
  for label,box in rs.items():
   for threshold in [100,120,140]:
    pts=[(x,y) for y in range(box[1],box[3]) for x in range(box[0],box[2]) if min(im.getpixel((x,y)))>threshold and max(im.getpixel((x,y)))-min(im.getpixel((x,y)))<30]
    if pts:
     xs,ys=zip(*pts);rows.append(dict(candidate=name,page=page,label=label,threshold=threshold,top=min(ys),bottom=max(ys)+1,height=max(ys)-min(ys)+1))
(root/'measurements.json').write_text(json.dumps(rows,indent=2)+'\n')
for row in rows:
 if row['threshold']==120:print(row)
# Simple nearest-neighbor enlargement of actual LRPS2 screenshots, with labels.
canvas=Image.new('RGB',(700,len(sources)*175),(20,20,20));draw=ImageDraw.Draw(canvas)
for i,(name,source) in enumerate(sources.items()):
 draw.text((5,i*175+3),name,fill='white')
 for j,page in enumerate(('alex-top','lily-top')):
  im=Image.open(source/(page+'.png')).crop((5,160,350,235)).resize((690,150))
  # Alex and Lily rows side by side reduced horizontal sample to retain readable letters.
  crop=Image.open(source/(page+'.png')).crop((125 if j==0 else 175,160,300 if j==0 else 350,235)).resize((350,150))
  canvas.paste(crop,(j*350,i*175+22))
canvas.save(root/'comparison.png')
