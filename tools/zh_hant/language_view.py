#!/usr/bin/env python3
"""Turn a private copy of the build inputs into a Traditional language's view (srwz.language).

build_editions.py --language zh-hant-tw / zh-hant-hk freezes its inputs through this tool: the copy's corpus/zh,
glossary, runtime keywords, layout word lists, codebook, font profile and texture configs become the Traditional
ones, and every file lock that names a replaced file follows. Taiwan text is the parallel corpus
(corpus/zh-hant); Hong Kong has its own parallel corpus (corpus/zh-hant-hk). The pipeline then builds the copy unchanged.

SP is built on a frozen baseline whose inherited text comes from the Original build. For --editions sp the view
also carries that baseline in the language (build_dual_sp.sp_prepare): the converters run here against the same
language's Original build (--answer-key), so the SP build itself stays the unchanged pipeline. The support trees
those steps need are placed in the copy for the duration; only frozen inputs remain in the snapshot.

Usage: language_view.py PROJECT --variant tw|hk [--editions original|sp]
                        [--answer-key DIR --taiwan-answer-key DIR --simplified-answer-key DIR]
Prints the frozen dependencies outside the source trees (SP's locked inputs) as a last line `additional: [...]`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / 'tools')]
import build_dual as bd  # noqa: E402
from srwz.release_inputs import copy_file  # noqa: E402

SP_SUPPORT_TREES = ['work/build/special-disc', 'work/disc', 'work/font-source', 'work/toolchain', 'work/writeback']


def place_sp_support(project: Path) -> None:
    import build_dual_sp as sp
    from special_disc.resource_view import enabled
    for tree in SP_SUPPORT_TREES:
        if enabled() and tree == 'work/build/special-disc':
            for child in (ROOT/tree).iterdir():
                if child.is_dir() and not child.name.startswith('full-text'):
                    shutil.copytree(child, project/tree/child.name, copy_function=copy_file, dirs_exist_ok=True)
            continue
        shutil.copytree(ROOT / tree, project / tree, copy_function=copy_file, dirs_exist_ok=True, symlinks=True)
    for rel in sp.SP_FILES:
        copy_file(ROOT / rel, project / rel)
    # files of the source trees that are not build inputs (editorial state, authoring tools) but that SP's
    # authoring steps read: present for these steps only
    for tree in ('config', 'tools'):
        for f in (ROOT / tree).rglob('*'):
            target = project / f.relative_to(ROOT)
            if f.is_file() and '__pycache__' not in f.parts and not target.exists():
                copy_file(f, target)
    # the discs, under both names the tools use (rom/ is the repository's alias of build/iso/sources/)
    for iso in ((ROOT / 'rom/original.iso').resolve(), (ROOT / sp.SP_ISO).resolve()):
        for directory in ('rom', 'build/iso/sources'):
            target = project / directory / iso.name
            if enabled():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(iso)
            else:
                copy_file(iso, target)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('project', type=Path)
    p.add_argument('--variant', choices=sorted(bd.VARIANTS), required=True)
    p.add_argument('--editions', default='original')
    p.add_argument('--answer-key', type=Path, help="this language's Original components (SP)")
    p.add_argument('--taiwan-answer-key', type=Path, help='the Taiwan Original components: shared pictures (SP)')
    p.add_argument('--simplified-answer-key', type=Path, help='the Simplified Original components (SP)')
    a = p.parse_args()
    project = a.project.resolve()
    editions = set(a.editions.split(','))
    if 'sp' in editions and editions != {'sp'}:
        raise SystemExit('a Traditional SP view carries SP-only inputs: build SP on its own')
    additional = []
    if 'sp' in editions:
        import build_dual_sp as sp
        place_sp_support(project)
        bd.prepare_tc(project, a.variant)
        if a.variant != 'tw':
            sp.sp_shared_from_taiwan(project)
        bd.menu_codebook(project)
        sp.sp_prepare(project, a.variant, a.answer_key.resolve(), a.taiwan_answer_key.resolve(),
                      a.simplified_answer_key.resolve())
        from srwz.sp_edition import locked_sp_inputs
        additional = list(locked_sp_inputs(project))
    else:
        bd.prepare_tc(project, a.variant)
        # A character the Traditional codebook lacks stops the build in its own font step (rebuild_zh_font.py
        # runs update_zh_release_font_snapshot.py read-only); growing the codebook is an authoring step.
        bd.menu_codebook(project)
    # The authored sections and file overlays are now applied: their stored copies are sources of the view, not
    # inputs of the build (they quote locks of the Simplified files they were authored beside).
    (project / 'config/zh-hant/sections.json').unlink(missing_ok=True)
    shutil.rmtree(project / 'config/zh-hant/overlay', ignore_errors=True)
    print('additional:', json.dumps(additional), flush=True)


if __name__ == '__main__':
    main()
