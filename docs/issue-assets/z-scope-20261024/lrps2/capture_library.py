"""SP library bodies (character: Alex Smith; robot: Mazinger Z) with punctuation.

The last three visible physical rows of the loaded body are replaced in RAM by
two blank rows and one sample row, then redrawn in place (a page re-entry would
regenerate the working copy from the archive). The frame-end record buffer
keeps the last drawn physical row, i.e. the sample. Per sample: untagged, and
tagged by the production `library_typography` compiler (the library does not
use <z>). Data bytes only; restored before quitting; ISO/card hashes asserted.

  python3 capture_library.py [character|robot ...]
"""
import concurrent.futures
import json
import sys

from capture_story import ROOT, Session, encoder, route as story_route, visible
from srwz.library_typography import library_typography
from srwz.text import two_byte_visible_spaces

SAMPLES = {
    'rx': 'RX-78F14型与99.9%的G-3',
    'dome': 'D.O.M.E.和A/B:C、（1+2）～3',
}
PAGES = {
    'character': dict(prefix='地球统合政府', visible_rows=9, domain='character'),
    'robot': dict(prefix='兜十藏博士', visible_rows=5, domain='robot'),
}


def route(page):
    flow, _ = story_route()
    if page == 'character':
        seq = [c['command'] for c in json.loads(
            (ROOT / 'work/runtime/lrps2/automatic-digits-characters-20261021/sp/receipt.json').read_text())['commands']]
        return seq, 'shot alex-top'
    return flow + ['press circle 3', 'run 240', 'shot robot-list',
                   'press circle 3', 'run 180', 'shot robot-body'], 'shot robot-body'


def capture(page, sample):
    spec, enc = PAGES[page], encoder()
    s = Session('current', f'library-{page}-{sample}')
    restored = []
    try:
        seq, stop = route(page)
        s.replay(seq, stop)
        hits = s.find(enc.encode(spec['prefix']))
        assert hits, 'body text not found'
        n = spec['visible_rows']
        blocks = {}
        for h in hits:
            raw = s.read(h, 4096)
            rows = raw[:raw.index(b'\0')].split(b'\n')
            assert len(rows) >= n, (hex(h), len(rows))
            start = h + sum(len(r) + 1 for r in rows[:n - 3])
            blocks[start] = b'\n'.join(rows[n - 3:n])
        variants = {'untagged': SAMPLES[sample],
                    'tagged': library_typography(SAMPLES[sample], 'DSC2', domain=spec['domain'])}
        s.report.update(page=page, sample=SAMPLES[sample], variants=variants, body_hits=[hex(h) for h in hits])
        for start, original in blocks.items():
            assert s.read(start, len(original)) == original
            restored.append((start, original))
        for name, text in variants.items():
            stored = two_byte_visible_spaces(text)
            payload = enc.encode('　') + b'\n' + enc.encode('　') + b'\n' + enc.encode(stored)
            for start, original in blocks.items():
                assert len(payload) <= len(original), (name, len(payload), len(original))
                pad = len(original) - len(payload)
                assert pad % 2 == 0, (name, pad)
                s.write(start, payload + bytes.fromhex('8140') * (pad // 2))
            s.cmd('run 30')
            s.shot(f'{name}', visible(stored))
            s.cmd('press down 3')
            s.cmd('run 20')
            s.cmd('press up 3')
            s.cmd('run 20')
            s.shot(f'{name}-scrolled', visible(stored))
    finally:
        for start, original in restored:
            try:
                s.write(start, original)
            except Exception as exc:  # report, keep closing
                s.report['restore_error'] = repr(exc)
        s.report['restored'] = len(restored)
        s.close()


if __name__ == '__main__':
    pages = sys.argv[1:] or list(PAGES)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(capture, p, smp) for p in pages for smp in SAMPLES]:
            future.result()
