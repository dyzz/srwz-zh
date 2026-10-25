"""SP stage-1 message window: natural <z> line and injected tag variants (LRPS2).

natural: replay the stored story route to line 01.01/0002 (“真是台奇怪的KLF。
是改装机吗？”, KLF in a compact scope) on the current SP ISO, which still
carries the old 22/22 width-only restore.

inject (current SP ISO; the native parser is unchanged, so injected bytes
render exactly as a build would store them): line 02.01/0005 of the replayed
briefing scene is replaced in RAM before it is shown by
one single-row sample in several encodings, so every glyph record of the row is
kept in the frame-end buffer. Only data bytes of the loaded script change; they
are restored before quitting, and ISO / memory-card hashes are asserted.

  python3 capture_story.py natural
  python3 capture_story.py walk       # 02.01/0005 onward, both ISOs, captures compact lines
  python3 capture_story.py synopsis   # episode 3 synopsis (013), both ISOs
  python3 capture_story.py inject [SAMPLE ...] [--variants plain,z-11-10]
"""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import re
import shutil
import socket
import struct
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from srwz.compact_scopes import STORY, expand_scope, SCOPE  # noqa: E402
from srwz.text import PreparedTextEncoder, CONTROL_NOTATION, two_byte_visible_spaces  # noqa: E402

WORK = ROOT / 'work/runtime/lrps2/z-scope-20261024'
CARD = Path('/Users/nate/Library/Application Support/ARMSX2/memcards/Mcd001.ps2')
ISOS = {'current': ROOT / 'build/iso/special-disc/sp-current.iso',
        'built': ROOT / 'build/iso/test/z-scope-20261024-sp.iso'}
FONT_STATE = 0x4ED5B0
RAM_SIZE = 0x2000000
OLD = '<width:0E><space:0C>{}<width:16><space:16>'
SAMPLES = {
    'klf': '“真是<z>KLF</z>的<z>013</z>号机吗？”',
    'rx': '“<z>RX-78F14</z>型、<z>99.9%</z>。”',
    'dome': '“<z>D.O.M.E.</z>与<z>G-3</z>！”',
    'slash': '“<z>A/B:C</z>和<z>（1+2）～3</z>”',
    'mk': '“<z>Mk-II</z>，<z>1,000</z>机”',
    'rock': "“<z>Rock'n Roll</z>：<z>x.y</z>”",
}
VARIANTS = {
    'plain': dict(scope=None),
    'old-22': dict(scope='old'),
    'z-11-10': dict(scope={**STORY, 'digit': 0x8A}),  # first <z> default: letters 11, digits 10
    'z': dict(scope=STORY),  # production default since the 2026-10-24 review: letters and digits 11
    'z-11up-10': dict(scope={**STORY, 'letter': 0x8B}),  # letters 11 + optical up1
    'z-12up-11': dict(scope={**STORY, 'letter': 0x8C, 'digit': 0x0B}),  # library character body set
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 << 20), b''):
            h.update(block)
    return h.hexdigest()


def encoder():
    import migrate_slps_text as mst
    from build_full_text import PROPOSAL
    table, _, overrides, _ = mst.encoding_tables(PROPOSAL)
    return PreparedTextEncoder(table, overrides)


def sample_text(sample, variant):
    scope, source = VARIANTS[variant]['scope'], SAMPLES[sample]
    if scope is None:
        text = SCOPE.sub(lambda m: m[1], source)
    elif scope == 'old':
        text = SCOPE.sub(lambda m: OLD.format(m[1]), source)
    else:
        text = SCOPE.sub(lambda m: expand_scope(m[1], scope), source)
    return two_byte_visible_spaces(text)


class Session:
    def __init__(self, variant, run_name):
        self.iso = ISOS[variant]
        self.run = WORK / f'{variant}-{run_name}'
        self.run.mkdir(parents=True, exist_ok=True)
        self.save = OUT / f'{variant}-{run_name}'
        self.save.mkdir(parents=True, exist_ok=True)
        self.sock = f'/tmp/srwz-z-scope-{variant}-{run_name}.sock'
        self.report = dict(variant=variant, run=run_name, iso=str(self.iso.relative_to(ROOT)),
                           iso_sha256=sha(self.iso), card_before=sha(CARD), commands=[], frames=[])
        self.log = (self.run / 'driver.log').open('w')
        self.proc = subprocess.Popen(
            ['arch', '-x86_64', str(ROOT / 'work/runtime/lrps2/python-x86_64-3.12.14/bin/python3'),
             str(ROOT / 'work/runtime/lrps2/interactive/lrps2_drive.py'),
             str(self.iso), str(CARD), str(self.run), self.sock],
            stdout=self.log, stderr=subprocess.STDOUT, cwd=ROOT)
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(600)
        deadline = time.monotonic() + 90
        while True:
            assert self.proc.poll() is None and time.monotonic() < deadline, 'driver did not start'
            try:
                s.connect(self.sock)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.2)
        self.f = s.makefile('rw')

    def cmd(self, c, record=True):
        self.f.write(c + '\n')
        self.f.flush()
        lines = []
        while True:
            line = self.f.readline()
            assert line, 'driver disconnected'
            lines.append(line.rstrip('\n'))
            if line.startswith(('OK', 'ERR')):
                break
        assert lines[-1].startswith('OK'), lines
        if record:
            self.report['commands'].append(dict(command=c, response=lines[-1]))
        return lines

    def read(self, address, size):
        return bytes.fromhex(self.cmd(f'mem {address:x} {size}', record=False)[0])

    def write(self, address, data):
        self.cmd(f'poke {address:x} {data.hex()}')
        assert self.read(address, len(data)) == data

    def shot(self, label, visible=None):
        self.cmd(f'shot {label}')
        shutil.copy2(self.run / f'{label}.png', self.save / f'{label}.png')
        state = self.read(FONT_STATE, 0x90)
        pointer = struct.unpack_from('<I', state, 0x58)[0]
        raw = self.read(pointer, 10240)
        rows = [list(struct.unpack_from('<2h', raw, i * 32 + 4)) + list(struct.unpack_from('<2h', raw, i * 32 + 12))
                for i in range(320)]
        glyphs = [r for r in rows if r != [0, -200, 1, 1]]
        frame = dict(name=label, screenshot_sha256=sha(self.save / f'{label}.png'),
                     explicit_whdxdy=list(struct.unpack_from('<4h', state, 0x14)), glyph_records=glyphs)
        if visible is not None:
            frame['glyphs'] = [dict(char=c, x=r[0], y=r[1], w=r[2], h=r[3]) for c, r in zip(visible, glyphs)]
        self.report['frames'].append(frame)
        print(self.report['variant'], self.report['run'], label, flush=True)

    def replay(self, commands, stop_after):
        for c in commands:
            verb = c.split()[0]
            if verb in ('run', 'press'):
                self.cmd(c)
            elif verb == 'shot':
                self.shot(c.split()[1])
            if c == stop_after:
                return
        raise AssertionError(f'route has no {stop_after!r}')

    def find(self, needle, lo=0x100000, hi=RAM_SIZE, chunk=1 << 20):
        hits, address = [], lo
        while address < hi:
            size = min(chunk, hi - address)
            data = self.read(address, min(size + len(needle), RAM_SIZE - address))
            i = data.find(needle)
            while i != -1:
                if i < size:
                    hits.append(address + i)
                i = data.find(needle, i + 1)
            address += size
        return sorted(set(hits))

    def close(self):
        try:
            self.cmd('quit')
        finally:
            self.f.close()
            if self.proc.poll() is None:
                self.proc.wait(timeout=60)
            self.log.close()
            self.report['card_after'] = sha(CARD)
            self.report['iso_after'] = sha(self.iso)
            (self.save / 'receipt.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n')
            assert self.report['card_after'] == self.report['card_before']
            assert self.report['iso_after'] == self.report['iso_sha256']


def route():
    flow = [c['command'] for c in json.loads(
        (ROOT / 'docs/issue-assets/automatic-digits-20261021/flow/sp/receipt.json').read_text())['commands']]
    story = [c['command'] for c in json.loads(
        (ROOT / 'work/runtime/lrps2/automatic-digits-20261021/sp/story-replay-receipt.json').read_text())['commands']]
    return flow[:flow.index('shot library-menu') + 1], story


def visible(text):
    return [c for c in CONTROL_NOTATION.sub('', text) if c != '\n']


def corpus_line(entry_id):
    entries = json.loads((ROOT / 'corpus/zh/special-disc/story-dialogue.json').read_text())['entries']
    return next(e['translation'] for e in entries if e['id'] == entry_id)


def natural(variant):
    flow, story = route()
    s = Session(variant, 'natural')
    try:
        s.replay(flow, 'shot library-menu')
        s.replay(story, 'shot story-dialogue-001')
        line = corpus_line('sd/story/001/dialogue/01.01/0002')
        s.report['line_0002'] = line
        s.cmd('press circle 3')
        s.cmd('run 120')
        s.shot('line-0002', visible(SCOPE.sub(lambda m: m[1], line)))
        s.cmd('run 120')
        s.shot('line-0002-settled', visible(SCOPE.sub(lambda m: m[1], line)))
    finally:
        s.close()


def walk(variant, presses=180, shots_from=95):
    """From line 02.01/0005, advance one line per circle press and keep a frame
    of every step from `shots_from` on (in the work run directory), which covers
    02.01/0084 (KLF) and 02.02/0026 (特命代码013). Map-scene dialogue does not
    use the briefing window's glyph record buffer, so lines are picked from the
    frames, not from records."""
    flow, story = route()
    s = Session(variant, 'walk')
    try:
        s.replay(flow, 'shot library-menu')
        s.replay(story, 'shot story-dialogue-001')
        for i in range(presses):
            s.cmd('press circle 3', record=False)
            s.cmd('run 100', record=False)
            if i >= shots_from:
                s.cmd(f'shot step-{i:03d}', record=False)
        s.report['presses'] = presses
    finally:
        s.close()


def synopsis(variant):
    """Full flow route: chart -> episode 3 synopsis (013, untagged, native auto digit)."""
    flow = [c['command'] for c in json.loads(
        (ROOT / 'docs/issue-assets/automatic-digits-20261021/flow/sp/receipt.json').read_text())['commands']]
    s = Session(variant, 'synopsis')
    try:
        s.replay(flow, 'shot target-reopened')
    finally:
        s.close()


def inject(sample, variant_name):
    flow, story = route()
    enc = encoder()
    s = Session('current', f'inject-{variant_name}' if sample == 'klf' else f'inject-{sample}-{variant_name}')
    restored = []
    try:
        s.replay(flow, 'shot library-menu')
        s.replay(story, 'shot story-dialogue-001')
        # The replayed scene is 02.01; line 0005 is shown on the next circle.
        target = two_byte_visible_spaces(corpus_line('sd/story/001/dialogue/02.01/0005'))
        needle = enc.encode(re.split(r'[\n<]', target)[0][:8])
        hits = s.find(needle)
        assert hits, 'line 0003 not found in RAM'
        text = sample_text(sample, variant_name)
        payload = enc.encode(text) + b'\0'
        s.report.update(sample=SAMPLES[sample], encoded_text=text, payload_hex=payload.hex(),
                        target_prefix_hex=needle.hex(), hits=[hex(h) for h in hits])
        for h in hits:
            old = s.read(h, 256)
            original = old[:old.index(b'\0') + 1]
            assert len(payload) <= len(original), (len(payload), len(original))
            s.write(h, payload.ljust(len(original), b'\0'))
            restored.append((h, original))
        s.cmd('press circle 3')
        s.cmd('run 150')
        s.shot('sample', visible(text))
        s.cmd('run 60')
        s.shot('sample-settled', visible(text))
    finally:
        for h, original in restored:
            try:
                s.write(h, original)
            except Exception as exc:  # report, keep closing
                s.report['restore_error'] = repr(exc)
        s.report['restored'] = len(restored)
        s.close()


if __name__ == '__main__':
    mode = sys.argv[1]
    # inject [SAMPLE ...] [--variants a,b]: default every sample x every variant.
    args = sys.argv[2:]
    variants = list(VARIANTS)
    if '--variants' in args:
        variants = args[args.index('--variants') + 1].split(',')
        args = args[:args.index('--variants')]
    jobs = ([(natural, (v,)) for v in ISOS] if mode == 'natural'
            else [(walk, (v,)) for v in ISOS] if mode == 'walk'
            else [(synopsis, (v,)) for v in ISOS] if mode == 'synopsis'
            else [(inject, (smp, v)) for smp in (args or SAMPLES) for v in variants])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(fn, *arg) for fn, arg in jobs]:
            future.result()
