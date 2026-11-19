"""Fill missing Taiwan and Hong Kong translations from Simplified before freezing build inputs."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import derive_hk
import regional_terms
import sync_corpus as sc

MISSING = object()


def fill(source, existing, *, keys=('id', 'entry_index')):
    """Keep authored values; align records by identity and schema-defined positional arrays by index."""
    if existing is MISSING or existing is None:
        return source
    if isinstance(source, dict):
        result = dict(existing)
        for field, value in source.items():
            result[field] = fill(value, result.get(field, MISSING), keys=keys)
        return result
    if isinstance(source, list):
        rows = list(existing)
        # Some tables have native keys instead of an id, e.g. terrain names,
        # numbered tutorial pages, or the [first, last] range of a roster segment.
        for identity in dict.fromkeys((*keys, 'shared_id', 'chunk_index', 'page', 'source', 'range')):
            if not source or not all(isinstance(e, dict) and identity in e for e in source):
                continue
            def row_key(row):
                return json.dumps(row[identity], sort_keys=True, ensure_ascii=False)
            if len({row_key(e) for e in source}) != len(source):
                continue
            indexed = {row_key(e): e for e in rows}
            if len(indexed) != len(rows):
                raise ValueError(f'duplicate {identity} in regional corpus')
            result = [fill(e, indexed.pop(row_key(e), MISSING), keys=keys) for e in source]
            if indexed:
                raise ValueError(f'regional records missing from Simplified: {list(indexed)[:3]}')
            return result
        for i, value in enumerate(source):
            if i < len(rows):
                rows[i] = fill(value, rows[i], keys=keys)
            else:
                rows.append(value)
        return rows
    if isinstance(source, str) and source.strip() and isinstance(existing, str) and not existing.strip():
        return source
    return existing


def identity(path):
    if not path.exists():
        return None
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def prepare(root: Path) -> None:
    cache = root / 'work/cache/editions/multilang/corpus-coverage.json'
    try:
        previous = json.loads(cache.read_text())
    except (FileNotFoundError, ValueError):
        previous = {}
    policy = identity(Path(__file__))
    if previous.get("policy") != policy:
        previous = {}
    checked = {"policy": policy}
    drafter = sc.Drafter(root / 'config/zh-hant/bootstrap.json')
    chars = derive_hk.char_table()
    changes = []
    for src, tw, _ in sc.TREES:
        source_files = set((root / src).rglob('*.json'))
        expected = {f.relative_to(root / src) for f in source_files}
        for tree in (tw, tw + '-hk'):
            extras = {f.relative_to(root / tree) for f in (root / tree).rglob('*.json')} - expected
            if extras:
                raise ValueError(f"{tree}: regional files missing from Simplified: {sorted(extras)[:3]}")
        for path in sorted(source_files):
            rel = path.relative_to(root / src)
            targets = [root / tree / rel for tree in (tw, tw + '-hk')]
            paths = [path, *targets]
            name = str(path.relative_to(root))
            before = [identity(p) for p in paths]
            if previous.get(name) == before:
                checked[name] = before
                continue
            source = json.loads(path.read_text())
            special = src == 'corpus/zh' and rel.parts[0] == sc.SP_TREE
            drafter.frozen = (sc.FROZEN_KEYS - {'review_history'}) | sc.SP_FROZEN if special else sc.FROZEN_KEYS
            keys = ('id', 'entry_index', 'source') if special else ('id', 'entry_index')
            for region, target in zip(('tw', 'hk'), targets):
                old = json.loads(target.read_text()) if target.exists() else MISSING

                if fill(source, old, keys=keys) != old:
                    # Draft using the same dictionaries, source-bound terms and provenance as the
                    # authoring tools, then copy only the missing values into the regional document.
                    sc.KEY_FIELDS = keys
                    draft = sc.sync_document(source, None, drafter, str(rel), Counter())
                    tw_draft = regional_terms.apply_doc(source, draft, 'tw', drafter.frozen, keys, {},
                                                        fixed=regional_terms.length_bound(f'{tw}/{rel}'))
                    proposal = tw_draft
                    if region == 'hk':
                        proposal = regional_terms.apply_doc(source, tw_draft, 'hk', drafter.frozen, keys, {},
                                                            fixed=regional_terms.length_bound(f'{tw}/{rel}'))
                        proposal = derive_hk.forms(proposal, chars, drafter.frozen, {})
                        proposal = derive_hk.apply_overrides(proposal, tw_draft, f'{tw}/{rel}', {})
                    resolved = fill(proposal, old, keys=keys)
                    if identity(target) != before[1 if region == 'tw' else 2]:
                        raise ValueError(f'corpus changed during fallback: {target}')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_suffix('.json.tmp')
                    temp.write_text(json.dumps(resolved, ensure_ascii=False, indent=2) + '\n')
                    temp.replace(target)
                    changes.append(str(target.relative_to(root)))
            if identity(path) != before[0]:
                raise ValueError(f'Simplified corpus changed during fallback: {path}')
            checked[name] = [identity(p) for p in paths]
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_suffix('.tmp')
    temp.write_text(json.dumps(checked))
    temp.replace(cache)
    print(f'OpenCC fallback: {len(changes)} files', *changes, sep='\n')


if __name__ == '__main__':
    prepare(sc.ROOT)
