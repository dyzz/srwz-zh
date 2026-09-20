"""Read-only check of SP paths and locked preview inputs. No build or API calls."""
from pathlib import Path
import ast
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    config = json.loads((ROOT / 'config/products/special-disc/workspace.json').read_text())
    errors = []
    aliases = 0
    for section in ('directory_aliases', 'metadata_aliases', 'source_aliases'):
        for old, new in config[section].items():
            aliases += 1
            if not (ROOT / new).exists():
                errors.append(f'missing target: {new}')
            if not (ROOT / old).exists() or (ROOT / old).resolve() != (ROOT / new).resolve():
                errors.append(f'broken compatibility path: {old} -> {new}')
    lock = ROOT / config['preview_assets']
    assets = json.loads(lock.read_text())['files']
    for name in config.get('local_inputs', []):
        if not (ROOT / name).is_file():
            errors.append(f'missing local input: {name}')
    for asset in assets:
        path = lock.parent / 'preview' / asset['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
            errors.append(f'preview asset missing or changed: {asset["path"]}')
    sources = sorted((ROOT / 'tools/special_disc').rglob('*.py'))
    for source in sources:
        try:
            ast.parse(source.read_text(), filename=str(source))
        except SyntaxError as error:
            errors.append(str(error))
    print(json.dumps({'aliases_checked': aliases, 'assets_checked': len(assets),
                      'python_sources_checked': len(sources), 'errors': errors}, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
