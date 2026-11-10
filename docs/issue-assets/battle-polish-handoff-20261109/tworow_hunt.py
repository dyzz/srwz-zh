"""Replay a battle from a savestate with varied start delays until the game draws a
two-row subtitle; screenshot it and record both rows with their positions.

  PYTHONPATH=tools python3 tworow_hunt.py EDITION SOCK OUTDIR STATE BUTTON
"""
import json, socket, sys
from pathlib import Path
sys.path[:0] = ['tools']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P

edition, sock, out, state, button = sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve(), sys.argv[4], sys.argv[5]
out.mkdir(parents=True, exist_ok=True)
book = P.load_codebook()
vm = Armsx2Session(Path('unused'), Path('unused'), out)
vm._socket = socket.socket(socket.AF_UNIX); vm._socket.connect(sock)
vm._stream = vm._socket.makefile('rw')
found = []
for wait in (3, 17, 41, 73, 109, 151, 197, 239):
    vm.cmd('untrace'); vm.cmd('load ' + state); vm.run(wait)
    for c in P.trace_commands(edition): vm.cmd(c)
    vm.press(button, 3); seen = set(); first = None
    for n in range(150):
        vm.run(30)
        d = out / 't.jsonl'; vm.cmd(f'tracedump {d}')
        rows = [r for r in P.unique_rows(P.glyph_rows(P.read_hits(d), book)) if 70 <= r.y <= 110]
        for r in rows:
            if (r.y, r.text) not in seen:
                seen.add((r.y, r.text))
                if first is None and r.y == 84: first = n
        second = [r for r in rows if r.y == 96 and r.text.startswith('　')]
        if second:
            top = [r for r in rows if r.y == 84]
            name = f'tworow-{len(found)+1:02d}'
            vm.shot(name)
            found.append({'wait': wait, 'shot': name + '.png', 'rows': [{'y': r.y, 'xStart': r.x_start, 'xEnd': r.x_end, 'text': r.text} for r in top + second]})
            print(wait, [(r.y, r.x_start, r.x_end, r.text) for r in top + second], flush=True)
            break
        if first is not None and n > first + 70: break
    print('wait', wait, 'rows', len(seen), 'found', len(found), flush=True)
    if len(found) >= 2: break
vm.cmd('untrace')
(out / 'tworow.json').write_text(json.dumps({'edition': edition, 'found': found}, ensure_ascii=False, indent=1) + '\n')
