"""Advance a running session with BUTTON until the game draws a story dialogue whose
continuation row starts with the indent glyph; record glyph codes and X positions.

  PYTHONPATH=tools python3 story_align.py EDITION SOCK OUTDIR [BUTTON [COUNT]]
"""
import json, socket, sys
from pathlib import Path
sys.path[:0] = ['tools']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P
from srwz import continuation_indent

edition, sock, out = sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve()
button = sys.argv[4] if len(sys.argv) > 4 else 'circle'
wanted = int(sys.argv[5]) if len(sys.argv) > 5 else 2
out.mkdir(parents=True, exist_ok=True)
book = P.load_codebook()
vm = Armsx2Session(Path('unused'), Path('unused'), out)
vm._socket = socket.socket(socket.AF_UNIX); vm._socket.connect(sock)
vm._stream = vm._socket.makefile('rw')
for c in P.trace_commands(edition): vm.cmd(c)
found = []; seen = set()
for n in range(260):
    vm.run(40)
    d = out / 't.jsonl'; vm.cmd(f'tracedump {d}')
    rows = sorted(P.unique_rows(P.glyph_rows(P.read_hits(d), book)), key=lambda r: (r.frame, r.y))
    by_frame = {}
    for r in rows: by_frame.setdefault(r.frame, []).append(r)
    hit = None
    for frame_rows in by_frame.values():
        for a, b in zip(frame_rows, frame_rows[1:]):
            if a.glyphs[0].char in continuation_indent.OPENERS and b.glyphs[0].code in (continuation_indent.CODE, 0x8140) and len(b.glyphs) > 1 and a.x_start == b.x_start and 0 < b.y - a.y < 30:
                hit = (a, b)
    if hit and hit[0].text not in seen:
        a, b = hit; seen.add(a.text)
        name = f'story-{len(found)+1:02d}'; vm.run(60); vm.shot(name)
        found.append({'shot': name + '.png', 'row1': a.text, 'row2': ''.join(g.char for g in b.glyphs[1:]),
                      'indentCode': f'{b.glyphs[0].code:04X}', 'row1Glyphs': [[g.char, g.x] for g in a.glyphs[:3]],
                      'row2Glyphs': [[f'{g.code:04X}' if i == 0 else g.char, g.x] for i, g in enumerate(b.glyphs[:3])],
                      'firstTextX': a.glyphs[1].x, 'continuationTextX': b.glyphs[1].x, 'aligned': a.glyphs[1].x == b.glyphs[1].x})
        print(found[-1], flush=True)
        if len(found) >= wanted: break
    vm.press(button, 3)
vm.cmd('untrace'); (out / 't.jsonl').unlink(missing_ok=True)
(out / 'story-align.json').write_text(json.dumps({'edition': edition, 'found': found}, ensure_ascii=False, indent=1) + '\n')
print('found', len(found), [f['aligned'] for f in found])
