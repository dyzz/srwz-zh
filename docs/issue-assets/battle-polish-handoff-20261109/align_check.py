"""Cold-boot one edition, reach a battle, and check that the continuation row of a
two-row subtitle starts under the first row's text.

A savestate cannot be used: the metric table lives in EE RAM, so an older state keeps
the older metrics. ROUTE is a text file of runner commands that ends one confirm away
from a battle; the script then presses BUTTON and reads the glyph records.

  PYTHONPATH=tools python3 align_check.py EDITION ISO CARD OUTDIR ROUTE BUTTON [metal]
"""
import json, sys
from pathlib import Path
sys.path[:0] = ['tools']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P

edition, iso, card, out, route, button = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]).resolve(), Path(sys.argv[5]), sys.argv[6]
kw = dict(renderer='metal', upscale=4) if len(sys.argv) > 7 else {}
out.mkdir(parents=True, exist_ok=True)
book = P.load_codebook(); found = []; lines = []
with Armsx2Session(iso, card, out, **kw) as vm:
    for command in route.read_text().splitlines():
        if command.strip() and not command.startswith('#'): vm.cmd(command.strip())
    vm.shot('route-end')
    for c in P.trace_commands(edition): vm.cmd(c)
    vm.press(button, 3); presses = []; checkpoint = None
    for n in range(420 if edition == 'sp' else 1400):
        # Long traced runs exhaust the runner's memory and its screenshots turn black, so
        # keep a rolling savestate and the presses since it; replay_shot.py redraws the
        # found line in a clean session.
        if n % 25 == 0:
            checkpoint = f'ckpt-{(n // 25) % 2}'; vm.cmd('state ' + checkpoint); presses = []; base = n
        vm.run(30)
        d = out / 't.jsonl'; vm.cmd(f'tracedump {d}')
        rows = [r for r in P.unique_rows(P.glyph_rows(P.read_hits(d), book)) if 70 <= r.y <= 110]
        texts = {r.text for r in rows}
        for r in rows:
            if r.y == 84 and r.text not in lines: lines.append(r.text)
        second = [r for r in rows if r.y == 96 and r.text.startswith('　')]
        top = [r for r in rows if r.y == 84 and r.text.startswith('“') and not r.text.endswith('”')]
        if second and top:
            key = top[-1].text + second[-1].text
            if key not in [f['key'] for f in found]:
                name = f'aligned-{len(found)+1:02d}'; vm.shot(name)
                a, b = top[-1].glyphs, second[-1].glyphs
                found.append({'key': key, 'shot': name + '.png',
                              'row1': [[g.char, g.x] for g in a[:3]], 'row2': [[g.char, g.x] for g in b[:3]],
                              'firstTextX': a[1].x, 'continuationTextX': b[1].x, 'aligned': a[1].x == b[1].x,
                              'checkpoint': checkpoint + '.p2s', 'stepsAfterCheckpoint': n - base + 1, 'pressesAfterStep': list(presses)})
                print(found[-1], flush=True)
                if len(found) >= (2 if edition == 'sp' else 1): break
        elif edition != 'sp' and (any('开始战斗' in t for t in texts) or not rows) and n % 2 == 0:
            vm.press('circle', 3); presses.append(n - base + 1)
    vm.cmd('untrace')
(out / 't.jsonl').unlink(missing_ok=True)
(out / 'align.json').write_text(json.dumps({'edition': edition, 'iso': str(iso), 'linesDrawn': len(lines), 'found': found}, ensure_ascii=False, indent=1) + '\n')
print('lines', len(lines), 'two-row', len(found), 'aligned', [f['aligned'] for f in found])
