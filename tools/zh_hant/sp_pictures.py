"""Install the frozen Traditional SP pictures in the SP build clone."""
import shutil
from pathlib import Path

from locks import refresh_locks


def install_sp_pictures(clone: Path) -> None:
    source = clone / 'config/zh-hant/hand-drawn/sp'
    manifest = Path('config/assets/special-disc/preview.json')
    if not (source / manifest).is_file():
        raise FileNotFoundError(source / manifest)
    changed = []
    for path in sorted(source.rglob('*')):
        if path.is_file():
            rel = path.relative_to(source)
            shutil.copyfile(path, clone / rel)
            changed.append(str(rel))
    print('Traditional SP picture inputs:', len(changed), 'locks refreshed:', refresh_locks(clone, changed), flush=True)
