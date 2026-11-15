"""v0.5.0 vs current (v0.5.1 candidate) mixed Chinese/Latin screenshots, cold boot on both.

    python3 work/review/latin-compare-v051-20261115/capture.py EDITION v050|v051 [scene ...]

Routes are the run/press commands of the 2026-11-08 acceptance log. Each scene is reached from a
savestate made earlier in the *same* session (same ISO), never from another build's state.
For every scene: a shot of the text the game shows by itself, then the same sample text written
into the display buffer of both builds (found by searching RAM for the codes the game just drew).
"""
import hashlib, json, struct, sys, unicodedata
from pathlib import Path
R = Path.cwd(); HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(R / 'tools'), str(R / 'work/review/mixed-latin-runtime-20261112'), str(HERE)]
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P
from samples import code
from texts import SAMPLES

edition, version, *only = sys.argv[1:]
RENDERER, UPSCALE = ('sw', 1) if version.endswith('-sw') else ('metal', 4)
base = version.split('-')[0]
if base == 'v050':
    iso = R / f'build/iso/v0.5.0/srwz-zh-v0.5.0-{edition}.iso'
else:  # the v0.5.0+20261114 build the page was shot from, kept as an APFS clone (current-*.iso has moved on)
    iso = R / dict(original='build/iso/zh-release-original/current-original.iso', best='build/iso/zh-release-best/current-best.iso', sp='build/iso/special-disc/sp-current.iso')[edition]
out = HERE / 'runs' / f'{edition}-{version}'; out.mkdir(parents=True, exist_ok=True)
card = R / f'work/runtime/armsx2/formal-tag-free-20261108/{edition}/save/Mcd001.ps2'
LOG = [json.loads(l)['command'] for l in (R / 'work/runtime/armsx2/formal-tag-free-20261108/commands.jsonl').open()]
book = P.load_codebook(); SUBMIT = P.GLYPH_RECORD_PC[edition] + 0x10

# edition -> (boot slice, {scene: (slices from the cold-title state, text row index, logged buffer)})
ROUTES = {
    'original': ((741, 754), {
        'weapon': ([(756, 770)], 0x740890),
        'scroll': ([(813, 829)], 0x111c900),
        'story': ([(813, 879)], 0x10d6e8c),
        'map': ([(813, 879)], None),
        'robot': ([(962, 974)], None),
    }),
    'best': ((408, 421), {
        'weapon': ([(423, 437)], 0x741090),
        'scroll': ([(484, 500)], 0x111c900),
        'story': ([(484, 554)], 0x10d6e8c),
        'library': ([(637, 652)], 0xc44b04),
        'flow': ([(637, 703)], 0x75efa0),
    }),
    'sp': ((121, 134), {
        'weapon': ([(136, 154)], 0x7e6590),
        'battle': ([(136, 154), (362, 370)], 0x6899c8),
        'library': ([(197, 265)], 0xd6d8c0),
        'flow': ([(197, 328)], 0x8093e0),
        'scroll': ([(992, 1019)], 0x100fdc0),
    }),
}

def enc(text, indent=True):
    b = bytearray()
    for i, row in enumerate(text.split('\n')):
        if i: b += b'\n'
        for j, ch in enumerate(row):
            c = 0x93FD if indent and i and j == 0 and ch == '　' and text[0] in '“‘（《【' else 0x8140 if ch == '　' else code(ch)
            b += c.to_bytes(2, 'big')
    return bytes(b)

def replay(vm, a, b):
    for command in LOG[a:b]:
        op, *x = command.split()
        if op == 'run': vm.run(int(x[0]))
        elif op == 'press': vm.press(x[0], int(x[1]))

def records(vm, tag, shot=True):
    vm.cmd(f'trace {SUBMIT:x} name=glyph @{P.GLYPH_CODE_ADDRESS:x}:2 s0:20')
    vm.run(2); d = out / f'{tag}.jsonl'; vm.cmd(f'tracedump {d}'); vm.cmd('untrace')
    if shot: vm.shot(tag)
    hits = [h for h in P.read_hits(d) if h.get('name') == 'glyph']; d.unlink(missing_ok=True)
    if not hits: return []
    last = max(h['frame'] for h in hits); rows = {}
    for h in hits:
        if h['frame'] != last: continue
        r = struct.unpack('<10h', bytes.fromhex(h['mem']['s0:20']))
        c = int.from_bytes(bytes.fromhex(h['mem'][f'@{P.GLYPH_CODE_ADDRESS:x}:2']), 'little')
        rows.setdefault(r[3], []).append((r[2], c, r[6], r[7]))
    return [dict(y=y, codes=[g[1] for g in sorted(v)], x=[g[0] for g in sorted(v)], size=sorted({(g[2], g[3]) for g in v}),
                 text=''.join(unicodedata.normalize('NFKC', P.decode_code(g[1], book)) for g in sorted(v))) for y, v in sorted(rows.items())]

def find_buffers(vm, rows, n=6):
    """RAM offsets where the text of a drawn row starts, per row."""
    p = out / 'ram.bin'; vm.cmd(f'dump 0 33554432 {p}'); ram = p.read_bytes(); p.unlink()
    found = {}
    for i, row in enumerate(rows):
        want = b''.join(c.to_bytes(2, 'big') for c in row['codes'][:n])
        if len(want) < 6: continue
        hits = []; at = -1
        while (at := ram.find(want, at + 1)) >= 0 and len(hits) < 12: hits.append(at)
        found[i] = hits
    return found, ram

report = dict(edition=edition, version=version, iso=str(iso.relative_to(R)), sha256=hashlib.file_digest(iso.open('rb'), 'sha256').hexdigest(),
              renderer=RENDERER, upscale=UPSCALE, scenes={})
def save(): (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))

boot, scenes = ROUTES[edition]
with Armsx2Session(iso, card, out, renderer=RENDERER, upscale=UPSCALE) as vm:
    replay(vm, *boot); vm.shot('cold-title'); vm.cmd('state cold-title')
    for name, (slices, logged) in scenes.items():
        if only and name not in only: continue
        try:
            vm.cmd('load cold-title'); vm.run(2)
            for a, b in slices: replay(vm, a, b)
            if name == 'map':
                for n in range(500):
                    vm.press('circle', 3); vm.run(40)
                    if any('那家伙是THE' in r['text'] for r in records(vm, 'cur', shot=False)): break
                else: raise RuntimeError('map line not reached')
                vm.run(60)
            rows = records(vm, f'{name}-natural')
            sc = report['scenes'][name] = dict(natural=rows, samples={}); save()
            spec = SAMPLES.get(f'{edition}/{name}') or SAMPLES.get(name) or {}
            found, ram = find_buffers(vm, rows, spec.get('n', 6))
            sc['buffers'] = {str(rows[i]['y']): [hex(h) for h in v] for i, v in found.items()}
            if logged is not None: sc['logged'] = dict(address=hex(logged), bytes=ram[logged:logged + 24].hex())
            save()
            if not spec: continue
            ys = [r['y'] for r in rows]; y = spec['y'][edition] if isinstance(spec['y'], dict) else spec['y']
            index = 0 if y == 'first' else ys.index(y)
            targets = found.get(index, [])
            if logged is not None and any(abs(t - logged) <= 16 for t in targets): targets = [t for t in targets if abs(t - logged) <= 16]
            if not targets: raise RuntimeError(f'buffer not found for row y={y}')
            sc['poke'] = [hex(t) for t in targets]
            vm.cmd(f'state {name}-sample-start')
            for key, text in spec['items'].items():
                vm.cmd(f'load {name}-sample-start')
                data = enc(text, spec.get('indent', True)) + bytes(2)
                if spec.get('field'): data = data.ljust(spec['field'], b'\0')
                for t in targets: vm.cmd(f'poke {t:x} {data.hex()}')
                vm.run(spec.get('settle', 30)); sc['samples'][key] = dict(text=text, rows=records(vm, f'{name}-{key}')); save()
        except Exception as error:
            report['scenes'].setdefault(name, {})['error'] = repr(error); save(); print('ERR', name, error, flush=True)
for name, sc in report['scenes'].items():
    print(name, sc.get('error', ''), [(r['y'], r['text'], r['size']) for r in sc.get('natural', [])][:8], sc.get('buffers'), sc.get('logged'), flush=True)
