"""Coverage check for the Taiwan and Hong Kong corpora (the build runs it): every file, record and field
Simplified has must exist in each regional tree. The text itself is static and maintained by hand.

    fill_corpora.py [--check]
"""
from __future__ import annotations

import json
from pathlib import Path


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


def prepare(root: Path, check: bool = True) -> None:
    """Stop when a regional tree misses a file, record or field that Simplified has. Each language's text is
    static and written by hand; nothing is drafted."""
    import sync_corpus
    sync_corpus.ROOT = root
    gaps = sync_corpus.missing_values('tw') + sync_corpus.missing_values('hk')
    extras = sync_corpus.orphans('tw') + sync_corpus.orphans('hk')
    if gaps or extras:
        raise SystemExit('regional corpora do not cover Simplified (each language is built from its own text; '
                         'write the missing text by hand):\n  ' + '\n  '.join(gaps + [f'{x} (no Simplified file)' for x in extras]))
    print('regional corpora cover Simplified')


if __name__ == '__main__':
    import sys
    prepare(Path(__file__).resolve().parents[2])
