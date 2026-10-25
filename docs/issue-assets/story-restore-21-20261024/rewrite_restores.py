"""Rewrite story compact-scope restores from 22 (0x16) to the native 21 (0x15).

Well-formed author scopes `<width:0E><space:0C>RUN` + 22/22 restore are
rewritten. The five orphan 22/22 restores in front of 一万两千 (stages 115,
119, 127; left over from translating 12000 into hanzi) get the same value.
Everything else stays byte-identical.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.compact_authoring import SCOPE, unscoped_text  # noqa: E402

FILES = sorted((ROOT / 'corpus/zh/story-dialogue').glob('stage-*.json')) + [
    ROOT / 'corpus/zh/story-system-dialogue.json',
    ROOT / 'corpus/zh/special-disc/story-dialogue.json',
    ROOT / 'corpus/zh/special-disc/challenge-dialogue.json',
]


def rewrite(match):
    if match['w']:
        if (match['w'], match['s']) != ('16', '16'):
            return match.group()
        restore = '<width:15><space:15>'
    else:
        if (match['rs'], match['rw']) != ('16', '16'):
            return match.group()
        restore = '<space:15><width:15>'
    return match.group()[:match.start('restore') - match.start()] + restore


report = {}
for path in FILES:
    before = path.read_text(encoding='utf-8')
    after = SCOPE.sub(rewrite, before)
    orphans = after.count('<width:16><space:16>一万两千')
    after = after.replace('<width:16><space:16>一万两千', '<width:15><space:15>一万两千')
    if after == before:
        continue
    assert unscoped_text(after.replace('<width:15><space:15>', '<width:16><space:16>')
                         .replace('<space:15><width:15>', '<space:16><width:16>')) == unscoped_text(before)
    json.loads(after)
    left = after.count('<width:16><space:16>') + after.count('<space:16><width:16>')
    report[str(path.relative_to(ROOT))] = dict(
        scopes=sum(1 for m in SCOPE.finditer(before) if '16' in (m['w'], m['rw'])),
        orphans=orphans, remaining_16=left)
    if '--write' in sys.argv:
        path.write_text(after, encoding='utf-8')
print(json.dumps(dict(files=len(report),
                      scopes=sum(r['scopes'] for r in report.values()),
                      orphans=sum(r['orphans'] for r in report.values()),
                      remaining_16={k: v['remaining_16'] for k, v in report.items() if v['remaining_16']}),
                 ensure_ascii=False, indent=1))
