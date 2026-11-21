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


def awaited_answer_keys(receipts: Path, variant: str):
    """Answer keys read from frontend receipts that the Original builds write while this view is being made
    (build_multilang.py): everything before the baseline runs meanwhile. An `abort` file there ends the wait."""
    def resolve():
        import time
        started = time.perf_counter()
        names = {variant: f'zh-hant-{variant}', 'tw': 'zh-hant-tw', 'sc': 'zh'}
        paths = {key: receipts / f'{name}.json' for key, name in names.items()}
        while not all(path.is_file() for path in paths.values()):
            if (receipts / 'abort').exists():
                raise SystemExit('the Original frontends were not rebuilt: nothing to compile from')
            if time.perf_counter() - started > 1800:
                raise SystemExit('timed out waiting for the Original frontends')
            time.sleep(0.2)
        print(f'[sp-view] waited-for-frontends: {time.perf_counter()-started:.2f}s', flush=True)
        key = lambda name: (ROOT / json.loads(paths[name].read_text())['workspace']
                            / 'work/build/zh-release-full-story/components').resolve()
        return key(variant), key('tw'), key('sc')
    return resolve


STAGES = ('font-configs', 'baseline-atlas')
STAGE_VERSION = 1            # raise when a stage starts to depend on something its record cannot see


def stage_scope(project: Path, variant: str, stage: str) -> dict:
    """What a stage can depend on without opening it through Python (srwz.step_memo): the tool sources, the
    interpreter and the programs it runs, the settings in the environment, and the files other programs read
    by name (xdelta3 decodes the baselines from the discs; the compressor is run, not read)."""
    import hashlib
    import os
    from srwz.file_identity import sha256_file
    tools = hashlib.sha256()
    for tree in ('tools', 'shared', 'vendor'):
        for f in sorted((project / tree).rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts:
                tools.update(f'{f.relative_to(project).as_posix()}\0{sha256_file(f)}\n'.encode())
    by_name = {}
    for pattern in ('work/build/special-disc/baselines/*', 'work/toolchain/srwz-compressor-rs/target/release/srwz-compress',
                    'rom/*', 'build/iso/sources/*'):
        for f in sorted(project.glob(pattern)):
            if f.is_file():
                by_name[f.relative_to(project).as_posix()] = sha256_file(f.resolve())
    programs = {}
    for name in ('node', 'xdelta3', 'python3'):
        path = shutil.which(name)
        programs[name] = [path, os.stat(path).st_size, os.stat(path).st_mtime_ns] if path else None
    settings = {k: v for k, v in sorted(os.environ.items())
                if k.startswith('SRWZ_') and k not in ('SRWZ_STEP_TRACE', 'SRWZ_SP_STAGE_VERIFY')}
    return dict(version=STAGE_VERSION, stage=stage, variant=variant, python=[sys.version, sys.executable],
                tools=tools.hexdigest(), by_name=by_name, programs=programs, settings=settings)


def run_stage(project: Path, variant: str, stage: str, keys=None) -> None:
    """One stage of sp_prepare as a process of its own, or the files it wrote the last time nothing it read
    has changed. Records live beside the region's view cache; a forced build has none (no SRWZ_SP_VIEW_CACHE)."""
    import os
    import subprocess
    command = [sys.executable, str(Path(__file__).resolve()), str(project), '--variant', variant,
               '--editions', 'sp', '--stage', stage]
    roots = {}
    if keys:
        for name, option, key in zip(('self', 'tw', 'sc'),
                                     ('--answer-key', '--taiwan-answer-key', '--simplified-answer-key'), keys):
            command += [option, str(key)]
            # an Original build's workspace: .../project/work/build/zh-release-full-story/components
            roots[f'frontend-{name}'] = Path(key).resolve().parents[3]
    cache = os.environ.get('SRWZ_SP_VIEW_CACHE')
    if not cache or os.environ.get('SRWZ_SP_STAGE_MEMO') == '0':
        subprocess.run(command, cwd=project, check=True)
        return
    from srwz.step_memo import Step
    from srwz.release_font import translation_selection_answer
    step = Step(f'sp-view-{stage}', Path(cache) / 'stages', project, ROOT, roots=roots,
                scope=stage_scope(project, variant, stage),
                # caches and outputs: nothing a stage's result may depend on
                ignore=('work/cache/', 'build/', 'work/editions/', 'work/build/sp-multilang-resources/'),
                untracked=('build.log',),      # the region's own log: the stages' output is appended to it
                probes={'translation-selection': translation_selection_answer},
                log=lambda line: print(line, flush=True))
    step.run(command, cwd=project, verify=os.environ.get('SRWZ_SP_STAGE_VERIFY') == '1')


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('project', type=Path)
    p.add_argument('--variant', choices=sorted(bd.VARIANTS), required=True)
    p.add_argument('--editions', default='original')
    p.add_argument('--answer-key', type=Path, help="this language's Original components (SP)")
    p.add_argument('--taiwan-answer-key', type=Path, help='the Taiwan Original components: shared pictures (SP)')
    p.add_argument('--simplified-answer-key', type=Path, help='the Simplified Original components (SP)')
    p.add_argument('--frontend-receipts', type=Path,
                   help='instead of the three answer keys: a directory where the Original builds will write them')
    p.add_argument('--stage', choices=STAGES, help='run one stage of the SP preparation in a prepared project')
    a = p.parse_args()
    project = a.project.resolve()
    if a.stage:
        import build_dual_sp as sp
        if a.stage == 'font-configs':
            sp.sp_stage_font_configs(project, a.variant)
        else:
            sp.sp_stage_baseline_atlas(project, a.variant, a.answer_key.resolve(), a.taiwan_answer_key.resolve(),
                                       a.simplified_answer_key.resolve())
        return
    editions = set(a.editions.split(','))
    if 'sp' in editions and editions != {'sp'}:
        raise SystemExit('a Traditional SP view carries SP-only inputs: build SP on its own')
    additional = []
    if 'sp' in editions:
        import build_dual_sp as sp
        place_sp_support(project)
        bd.prepare_tc(project, a.variant)
        if a.variant != 'tw':
            sp.sp_shared_pictures(project)
        bd.menu_codebook(project)
        sys.stdout.flush()
        run_stage(project, a.variant, 'font-configs')
        if a.frontend_receipts:
            keys = awaited_answer_keys(a.frontend_receipts.resolve(), a.variant)()
        else:
            keys = (a.answer_key.resolve(), a.taiwan_answer_key.resolve(), a.simplified_answer_key.resolve())
        sys.stdout.flush()
        run_stage(project, a.variant, 'baseline-atlas', keys)
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
