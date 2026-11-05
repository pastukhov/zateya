#!/usr/bin/env python3
"""Compile the actual host renderer, emit every state/rotation as PPM and a PNG sheet.
Usage: python3 firmware/tools/render-screen-previews.py /tmp/zateya-screen-previews
Requires a C compiler and Pillow (PNG sheet only).
"""
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/zateya-screen-previews')
out.mkdir(parents=True, exist_ok=True)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-I'+str(root/'include'),'-I'+str(root/'src'),str(root/'tools/screen-preview.c'),*[str(root/'src'/s) for s in ['screen_renderer.c','screen_ui.c','screen_orientation.c','screen_font.c','screen_font_data.c','vendor/qrcodegen.c']],'-o',str(out/'render')],check=True)
subprocess.run([str(out/'render'),str(out)],check=True)
from PIL import Image,ImageDraw
sheet=Image.new('RGB',(1000,5*290),(20,24,28))
draw=ImageDraw.Draw(sheet)
for row,name in enumerate(['recording','error','setup','ota','idle']):
 for col,r in enumerate([0,90,180,270]):
  im=Image.open(out/f'{name}-{r}-physical.ppm').rotate(r, expand=True)
  logical=Image.open(out/f'{name}-{r}.ppm')
  if im.tobytes()!=logical.tobytes():
   raise RuntimeError(f'physical transform inverse mismatch: {name} {r}')
  x=col*250+(250-im.width)//2;y=row*290+30
  sheet.paste(im,(x,y));draw.text((col*250+8,row*290+8),f'{name} {r}',fill='white')
sheet.save(out/'contact-sheet.png')
physical=Image.new('RGB',(4*155,5*270),(20,24,28))
draw=ImageDraw.Draw(physical)
for row,name in enumerate(['recording','error','setup','ota','idle']):
 for col,r in enumerate([0,90,180,270]):
  physical.paste(Image.open(out/f'{name}-{r}-physical.ppm'),(col*155+10,row*270+22))
  draw.text((col*155+5,row*270+4),f'{name} {r}',fill='white')
physical.save(out/'physical-sheet.png')
print(out/'contact-sheet.png')
