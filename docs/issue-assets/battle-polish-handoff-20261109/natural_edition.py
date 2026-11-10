"""In-battle readback of the 2026-11-09 line breaks on one edition.

Attaches to a running armsx2_drive.py session that sits one confirm away from a
battle, plays the battle, prints the subtitle rows the game drew, then searches RAM
for every battle line whose translation differs from HEAD (new break vs old break).

  PYTHONPATH=tools python3 natural_edition.py EDITION SOCK OUTDIR [BUTTON [REPEATS]]
"""
import json, socket, subprocess, sys
from pathlib import Path
sys.path[:0] = ['tools', 'tools/special_disc/writeback']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P
from migrate_slps_text import encoding_tables
from srwz.text import encode_text, two_byte_visible_spaces

edition, sock, out = sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve()
button = sys.argv[4] if len(sys.argv) > 4 else 'circle'
repeats = int(sys.argv[5]) if len(sys.argv) > 5 else 4
out.mkdir(parents=True, exist_ok=True)
book = P.load_codebook(); enc, _, codes, _ = encoding_tables()
vm = Armsx2Session(Path('unused'), Path('unused'), out)
vm._socket = socket.socket(socket.AF_UNIX); vm._socket.connect(sock)
vm._stream = vm._socket.makefile('rw')
for c in P.trace_commands(edition): vm.cmd(c)
seen = []; first = None
vm.press(button, 3)
for n in range(150):
    vm.run(30)
    if n < repeats * 2 and n % 2 == 1: vm.press(button, 3)
    d = out / 't.jsonl'; vm.cmd(f'tracedump {d}')
    for row in P.unique_rows(P.glyph_rows(P.read_hits(d), book)):
        key = (row.y, row.text)
        if 70 <= row.y <= 110 and key not in seen:
            seen.append(key); print(n, row.y, row.x_start, row.x_end, row.text, flush=True)
            if first is None: first = n
            if len(seen) <= 12: vm.shot(f'row-{len(seen):02d}')
    if first is not None and n > first + 60: break
vm.cmd('untrace')
vm.cmd(f'dump 0 33554432 {out}/ram.bin')
ram = (out / 'ram.bin').read_bytes()
doc = json.load(open('corpus/zh/battle/srvc-lines.json'))
old = {e['id']: e['translation'] for e in json.loads(subprocess.check_output(['git', 'show', 'HEAD:corpus/zh/battle/srvc-lines.json']))['entries']}
def blob(t, term): return encode_text(two_byte_visible_spaces(t.replace('\\n', '\n')), enc, overrides=codes, terminate=term).replace(b'\n', b'\\n')
hit = stale = 0; ex = []; bad = []
for e in doc['entries']:
    t = e['translation']
    if '<' in t or old[e['id']] == t: continue
    if ram.find(blob(t, True)) >= 0: hit += 1; ex.append(e['id'] + ' ' + t)
    elif ram.find(blob(old[e['id']], False)) >= 0: stale += 1; bad.append(e['id'])
(out / 'ram.bin').unlink()
res = {'edition': edition, 'rowsDrawn': [{'y': y, 'text': t} for y, t in seen], 'changedLinesInRam': hit, 'oldBreakInRam': stale, 'oldBreakIds': bad, 'examples': ex[:12]}
(out / 'natural.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
print('changed lines found in RAM with new break', hit, 'old-break found', stale); print(ex[:8])
