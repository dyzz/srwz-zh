"""Apply a completed source-bound story projection and remove obsolete z scopes.

Writes corpus/config only, never ISOs. All preimages are validated before any
write and retained in an audit directory; translated wording is not rewritten.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def integrate(root, projection, audit, prose=None):
    root, projection, audit = root.resolve(), projection.resolve(), audit.resolve()
    receipt = json.loads((projection / 'receipt.json').read_text())
    if not receipt.get('complete') or receipt.get('rejected') != 0 or not receipt.get('keywordOwnershipVerified'):
        raise ValueError('Story projection is incomplete or lacks source-owner binding')
    for name, record in receipt['inputs'].items():
        if digest((root / record['path']).read_bytes()) != record['sha256']:
            raise ValueError(f'Projection engine drift: {name}')
    originals, replacements = {}, {}
    def stage(path, raw):
        rel = path.relative_to(root).as_posix()
        originals[rel] = path.read_bytes() if path.exists() else None
        replacements[rel] = raw
    expected = {p.relative_to(root).as_posix() for p in (root / 'corpus/zh/story-dialogue').glob('stage-*.json')}
    if {f['source'] for f in receipt['files']} != expected:
        raise ValueError('Projection must cover the complete story corpus')
    for record in receipt['files']:
        source, candidate = root / record['source'], projection / record['candidate']
        if digest(source.read_bytes()) != record['sourceSha256']:
            raise ValueError(f'Story source changed: {record["source"]}')
        raw = candidate.read_bytes()
        if digest(raw) != record['candidateSha256']:
            raise ValueError(f'Projection bytes changed: {record["candidate"]}')
        stage(source, raw)
    if prose is not None:
        prose = prose.resolve()
        body = json.loads((prose / 'receipt.json').read_text())
        if not body.get('complete'):
            raise ValueError('Prose projection incomplete')
        required = {'corpus/zh/menu/stage-overviews.json', 'corpus/zh/summary.json', 'corpus/zh/battle/srvc-lines.json'}
        if {r['source'] for r in body['files']} != required:
            raise ValueError('Prose projection owner coverage mismatch')
        if body['inputs'] != receipt['inputs']:
            raise ValueError('Story and prose projections use different layout inputs')
        for record in body['files']:
            source, candidate = root / record['source'], prose / record['candidate']
            if digest(source.read_bytes()) != record['sourceSha256'] or digest(candidate.read_bytes()) != record['candidateSha256']:
                raise ValueError('Prose projection/source drift')
            stage(source, candidate.read_bytes())
    removed = 0
    def clean(value):
        nonlocal removed
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'translation' and isinstance(item, str):
                    depth = 0
                    import re
                    for match in re.finditer(r'</?z>', item):
                        depth += 1 if match[0] == '<z>' else -1
                        if depth not in (0, 1):
                            raise ValueError('Malformed compact scope in corpus')
                    if depth:
                        raise ValueError('Unclosed compact scope in corpus')
                    removed += item.count('<z>')
                    value[key] = item.replace('<z>', '').replace('</z>', '')
                else:
                    clean(item)
        elif isinstance(value, list):
            for item in value:
                clean(item)
    for path in (root / 'corpus/zh').rglob('*.json'):
        raw = replacements.get(path.relative_to(root).as_posix(), path.read_bytes())
        value = json.loads(raw)
        before = json.dumps(value)
        clean(value)
        if json.dumps(value) != before:
            stage(path, encoded(value))
    def locks(value):
        if isinstance(value, dict):
            rel = value.get('path')
            if isinstance(rel, str) and rel in replacements and 'sha256' in value:
                value.update(sha256=digest(replacements[rel]), size=len(replacements[rel]))
            for item in value.values():
                locks(item)
        elif isinstance(value, list):
            for item in value:
                locks(item)
    for path in (root / 'config').rglob('*.json'):
        value = json.loads(path.read_text())
        before = json.dumps(value)
        locks(value)
        if path.name == 'full-story-components.json':
            for row in value.get('runtime_keywords', {}).get('stage_relocations', []):
                row['relocation_offset'] = 'after_translated_donor'
        if path.name == 'story-component.json':
            value.pop('dialogue_typography', None)  # one project-wide policy
        if json.dumps(value) != before:
            stage(path, encoded(value))
    stage(root / 'config/text-layout/rendering-mode.json', encoded(dict(mode='proportional', chinese_punctuation='compact')))
    audit.mkdir(parents=True, exist_ok=False)
    result = {'projectionReceiptSha256': digest((projection / 'receipt.json').read_bytes()),
              'removedOtherScopes': removed, 'files': [], 'productionIsoWrites': False}
    for rel, raw in replacements.items():
        previous = originals[rel]
        if previous is not None:
            backup = audit / 'before' / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(previous)
        result['files'].append(dict(path=rel, before=digest(previous) if previous is not None else None, after=digest(raw)))
    (audit / 'plan.json').write_bytes(encoded(result))
    for rel, previous in originals.items():
        path = root / rel
        if (path.read_bytes() if path.exists() else None) != previous:
            raise ValueError(f'Concurrent source edit: {rel}')
    for rel, raw in replacements.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tag-free.tmp')
        temporary.write_bytes(raw)
        temporary.replace(path)
    (audit / 'complete.json').write_bytes(encoded(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projection', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--prose', type=Path, required=True)
    args = parser.parse_args()
    result = integrate(ROOT, args.projection, args.audit, args.prose)
    print(json.dumps({'files':len(result['files']), 'removedOtherScopes':result['removedOtherScopes']}))
