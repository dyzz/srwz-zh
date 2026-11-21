"""Coverage check for the Taiwan and Hong Kong corpora (the build runs it): every file, record and field
Simplified has must exist in each regional tree. The text itself is static and maintained by hand.

    fill_corpora.py [--check]
"""
from __future__ import annotations

import json
from pathlib import Path


def covers(source, regional, *, keys=('id', 'entry_index')):
    """Compare structure and text presence without constructing replacement translations."""
    if isinstance(source, dict):
        return isinstance(regional, dict) and all(
            field in regional and covers(value, regional[field], keys=keys)
            for field, value in source.items()
        )
    if isinstance(source, list):
        if not isinstance(regional, list):
            return False
        for identity in dict.fromkeys((*keys, 'shared_id', 'chunk_index', 'page', 'source', 'range')):
            if not source or not all(isinstance(row, dict) and identity in row for row in source):
                continue
            def identities(rows):
                return [json.dumps(row[identity], sort_keys=True, ensure_ascii=False) for row in rows]
            expected = identities(source)
            if len(set(expected)) == len(expected):
                if not all(isinstance(row, dict) and identity in row for row in regional):
                    return False
                if identities(regional) != expected:
                    return False
                break
        return len(regional) >= len(source) and all(
            covers(left, right, keys=keys) for left, right in zip(source, regional)
        )
    if isinstance(source, str):
        return isinstance(regional, str) and (not source.strip() or bool(regional.strip()))
    return regional is not None or source is None


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
