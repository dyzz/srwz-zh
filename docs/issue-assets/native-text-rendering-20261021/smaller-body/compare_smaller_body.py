from pathlib import Path
from PIL import Image,ImageDraw
R=Path.cwd();E=R/'docs/issue-assets/native-text-rendering-20261021';V=E/'smaller-body'
canvas=Image.new('RGB',(890,390),(20,20,20));draw=ImageDraw.Draw(canvas)
for i,(label,source) in enumerate((('Before: letters13 / digits12',E/'vertical-refinement/final/original'),('Smaller: letters12 / digits11',V/'final/original'))):
 draw.text((5,i*195+3),label,fill='white')
 for j,(page,left,right,x) in enumerate((('alex-top',125,300,0),('lily-top',90,350,360))):
  crop=Image.open(source/(page+'.png')).crop((left,160,right,245)).resize(((right-left)*2,170),Image.Resampling.NEAREST)
  canvas.paste(crop,(x,i*195+22))
canvas.save(V/'before-after.png')
alex=Image.new('RGB',(640,3*470),(20,20,20));draw=ImageDraw.Draw(alex)
for i,ed in enumerate(('original','best','sp')):
 draw.text((5,i*470+3),ed+' Alex smaller body',fill='white');alex.paste(Image.open(V/'final'/ed/'alex-top.png'),(0,i*470+22))
alex.save(V/'alex-review.png')
