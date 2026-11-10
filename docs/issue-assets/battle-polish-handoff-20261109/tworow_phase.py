"""Play on through an enemy phase (confirming each battle) until the game draws a
two-row subtitle; screenshot it and record the rows.

  PYTHONPATH=tools python3 tworow_phase.py EDITION SOCK OUTDIR STATE
"""
import json, socket, sys
from pathlib import Path
sys.path[:0] = ['tools']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P

edition, sock, out, state = sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve(), sys.argv[4]
out.mkdir(parents=True, exist_ok=True)
book = P.load_codebook()
vm = Armsx2Session(Path('unused'), Path('unused'), out)
vm._socket = socket.socket(socket.AF_UNIX); vm._socket.connect(sock)
vm._stream = vm._socket.makefile('rw')
vm.cmd('untrace'); vm.cmd('load ' + state); vm.run(5)
for c in P.trace_commands(edition): vm.cmd(c)
found = []; lines = []
for n in range(600):
    vm.run(30)
    d = out / 't.jsonl'; vm.cmd(f'tracedump {d}')
    rows = [r for r in P.unique_rows(P.glyph_rows(P.read_hits(d), book)) if 70 <= r.y <= 110]
    texts = {r.text for r in rows}
    for r in rows:
        if r.y == 84 and r.text not in lines: lines.append(r.text)
    second = [r for r in rows if r.y == 96 and r.text.startswith('　')]
    if second:
        top = [r for r in rows if r.y == 84]
        key = tuple(r.text for r in top + second)
        if key not in [tuple(x['text'] for x in f['rows']) for f in found]:
            name = f'tworow-{len(found)+1:02d}'; vm.shot(name)
            found.append({'step': n, 'shot': name + '.png', 'rows': [{'y': r.y, 'xStart': r.x_start, 'xEnd': r.x_end, 'text': r.text} for r in top + second]})
            print(n, key, flush=True)
            if len(found) >= 3: break
    elif any('开始战斗' in t for t in texts) or not rows:
        if n % 2 == 0: vm.press('circle', 3)
vm.cmd('untrace')
(out / 'tworow.json').write_text(json.dumps({'edition': edition, 'linesDrawn': lines, 'found': found}, ensure_ascii=False, indent=1) + '\n')
print('lines drawn', len(lines), 'two-row found', len(found))
