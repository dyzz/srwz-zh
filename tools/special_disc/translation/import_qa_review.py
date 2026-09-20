"""Import only the editable fields of a verified Q&A review ZIP (data only)."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'work/review/special-disc/qa-japanese-20260920'
NATIVE = ROOT / 'corpus/zh/special-disc/native-text.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def inspect(archive, baseline=BASE):
    manifest = json.loads((baseline / 'manifest.json').read_text())
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        require(sum(i.file_size for i in infos) < 16 * 1024 * 1024, 'ZIP too large')
        require(len({i.filename for i in infos}) == len(infos), 'Duplicate ZIP names')
        for i in infos:
            p = PurePosixPath(i.filename)
            require(not p.is_absolute() and '..' not in p.parts and
                    p.parts[0] == baseline.name and not stat.S_ISLNK(i.external_attr >> 16),
                    'Unsafe ZIP member')
        protected = []
        for name, lock in manifest['files'].items():
            original = (baseline / name).read_bytes()
            require(sha(original) == lock['sha256'], f'Baseline drift: {name}')
            if name == 'qa-review.json':
                continue
            require(z.read(baseline.name + '/' + name) == original, f'Protected file changed: {name}')
            protected.append(name)
        old = json.loads((baseline / 'qa-review.json').read_text())
        new = json.loads(z.read(baseline.name + '/qa-review.json'))
        require({k: v for k, v in old.items() if k != 'entries'} ==
                {k: v for k, v in new.items() if k != 'entries'}, 'Review schema drift')
        require(len(new['entries']) == len(old['entries']) == 37, 'Review count drift')
        frozen = lambda e: {k: v for k, v in e.items() if k not in ('review_translation', 'review_notes')}
        for a, b in zip(old['entries'], new['entries']):
            require(frozen(a) == frozen(b), 'Review ID/source/order drift')
            t = b['review_translation']
            require(isinstance(t, str) and t.strip() and isinstance(b['review_notes'], str), 'Empty review')
            require(not any(c in t for c in ('\0', '\r', '\ufffd', '[[', ']]', '\\n')), 'Invalid review text')
        return new['entries'], dict(package_sha256=sha(archive.read_bytes()),
            protected_files=len(protected), entry_count=37, page_count=22, metadata_count=15,
            immutable_sources_exact=True)


def run(archive, apply=False):
    entries, report = inspect(archive)
    before = NATIVE.read_bytes()
    doc = json.loads(before)
    by_id = {e['id']: e for e in doc['entries']}
    changed = []
    for e in entries:
        target = by_id[e['id']]
        require(target['source_text_sha256'] == e['source_text_sha256'] ==
                sha(target['source_text'].encode()), 'Corpus source drift')
        if target.get('qa_review_import', {}).get('package_sha256') == report['package_sha256']:
            require(target['translation'] == e['review_translation'], 'Imported translation drift')
            continue
        changed.append(e['id'])
        target.setdefault('review_history', []).append({k: target.get(k) for k in
            ('translation', 'review_author', 'review_notes', 'origin', 'writeback_status')})
        target.update(translation=e['review_translation'], review_notes=e['review_notes'],
            review_author='user-supplied Chinese revision', editorial_status='reviewed',
            origin='user-review:20260920-qa-chinese', writeback_status='binding_and_layout_pending',
            qa_review_import=dict(package_sha256=report['package_sha256'], source_text_sha256=e['source_text_sha256']))
    report.update(changed_ids=changed, corpus_before_sha256=sha(before), applied=apply)
    if apply:
        require(NATIVE.read_bytes() == before, 'Concurrent corpus change')
        NATIVE.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    report['corpus_after_sha256'] = sha(NATIVE.read_bytes())
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive', type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    report = run(args.archive, args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
