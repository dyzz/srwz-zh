"""Convert story compact scopes to the author notation <z>RUN</z>.

A scope `<width:0E><space:0C>RUN` + 21/21 restore becomes `<z>RUN</z>`. The
check per scope: expanding it again and dropping the new height tags gives the
old bytes back. The five orphan 21/21 restores in front of 一万两千 have no
opening scope; they only pushed the rest of the row into explicit mode with a
leftover height, so they are removed. Pass --write to change the corpus.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.compact_authoring import SCOPE  # noqa: E402
from srwz.compact_scopes import expand  # noqa: E402

FILES = sorted((ROOT / 'corpus/zh/story-dialogue').glob('stage-*.json')) + [
    ROOT / 'corpus/zh/story-system-dialogue.json',
    ROOT / 'corpus/zh/special-disc/story-dialogue.json',
    ROOT / 'corpus/zh/special-disc/challenge-dialogue.json',
]
HEIGHT = re.compile(r'<height:[0-9A-F]{2}>')
ORPHAN = '<width:15><space:15>一万两千'

report = dict(files={}, scopes=0, orphans_removed=0, kept=[])
for path in FILES:
    before = path.read_text(encoding='utf-8')

    def convert(match):
        restore = (match['w'], match['s']) if match['w'] else (match['rw'], match['rs'])
        new = f"<z>{match['visible']}</z>"
        if restore != ('15', '15') or HEIGHT.sub('', expand(new)) != match.group():
            report['kept'].append(dict(file=path.name, text=match.group()))
            return match.group()
        report['scopes'] += 1
        return new

    after = SCOPE.sub(convert, before)
    orphans = after.count(ORPHAN)
    after = after.replace(ORPHAN, '一万两千')
    report['orphans_removed'] += orphans
    if after != before:
        json.loads(after)
        report['files'][str(path.relative_to(ROOT))] = after.count('<z>')
        if '--write' in sys.argv:
            path.write_text(after, encoding='utf-8')
left = sum(path.read_text(encoding='utf-8').count('<width:15><space:15>') +
           path.read_text(encoding='utf-8').count('<space:15><width:15>') for path in FILES)
print(json.dumps(dict(files=len(report['files']), scopes=report['scopes'],
                      orphans_removed=report['orphans_removed'], kept=report['kept'],
                      restores_left_in_corpus=left if '--write' in sys.argv else None),
                 ensure_ascii=False, indent=1))
