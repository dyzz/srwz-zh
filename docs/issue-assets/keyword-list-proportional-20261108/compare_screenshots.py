"""Arrange equally sized crops of actual ARMSX2 captures; never redraw game text."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'work/runtime/armsx2/keyword-list-20261108'
rows=[('Side 3',1,140,1230),('Evidence 01',2,1310,365),('LOGOS',1,1310,940),('PLANT + Chinese',1,1310,1130)]
for edition in ['best','sp']:
 args=['/opt/homebrew/bin/magick','montage','-font','/System/Library/Fonts/Helvetica.ttc','-pointsize','28','-fill','white']
 for i,(label,page,x,y) in enumerate(rows):
  for variant in ['before','after']:
   p=OUT/edition/f'crop-{i}-{variant}.png'
   subprocess.run(['/opt/homebrew/bin/magick',str(OUT/edition/f'{variant}-page{page}.png'),'-crop',f'960x100+{x}+{y}','+repage',str(p)],check=True)
   args+=['-label',label+' / '+variant.upper(),str(p)]
 args+=['-tile','2x4','-geometry','+10+20','-background','#152127',str(OUT/edition/'comparison.png')]
 subprocess.run(args,check=True)
