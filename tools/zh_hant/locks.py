"""File locks of a project tree: {"path", "size", "sha256"} objects in its config/ JSON.

manifests/ are not touched: the build regenerates them (--refresh-manifest), and some lock config files that in
turn lock them, which would never settle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def refresh_locks(root: Path, changed) -> int:
    """Point every lock that names a changed file at its current bytes. A refreshed lock changes the file that
    holds it, so this repeats until nothing changes. Returns the number of locks updated."""
    configs = [p for p in (root / 'config').rglob('*.json') if 'zh-hant' not in p.relative_to(root).parts]
    refreshed, pending, rounds = 0, {str(c) for c in changed}, 0
    while pending:
        rounds += 1
        if rounds > 8:
            raise SystemExit(f'file locks do not settle (cycle?): {sorted(pending)}')
        current, pending = pending, set()
        for path in configs:
            text = path.read_text(encoding='utf-8')
            if not any(rel in text for rel in current):
                continue
            doc, hits = json.loads(text), []

            def walk(node):
                if isinstance(node, dict):
                    if node.get('path') in current and 'sha256' in node:
                        data = (root / node['path']).read_bytes()
                        digest = hashlib.sha256(data).hexdigest()
                        if node['sha256'] != digest or node.get('size', len(data)) != len(data):
                            node['sha256'] = digest
                            if 'size' in node:
                                node['size'] = len(data)
                            hits.append(node['path'])
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
            walk(doc)
            if hits:
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                refreshed += len(hits)
                pending.add(str(path.relative_to(root)))
    return refreshed
