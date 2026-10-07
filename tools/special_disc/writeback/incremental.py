"""Reuse SP components only with matching inputs and verified output bytes.

Code, configuration, font and baseline changes conservatively invalidate all
writers. Corpus dependencies are per writer; STAGE also binds to the actual
system STAGE bytes. Assembly and independent final ISO readback always run.
Cache receipts are published inside the final, independently verified report.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from srwz.edition import json_bytes, load_json, project_path
from srwz.release_inputs import copy_file, sha256_file, source_inventory
from srwz.sp_edition import locked_sp_inputs

COMPONENTS = ('system', 'stage', 'srvc', 'frame', 'image-labels')
CACHE_PATH = 'work/cache/sp-components'
SCHEMA = 1
CORPORA = {
    'system': ('corpus/zh/library/v0.2-reviewed.json', 'corpus/zh/library/sp-reviewed-supplement.json', 'corpus/zh/special-disc/system-text.json', 'corpus/zh/special-disc/frame-text.json'),
    'stage': ('corpus/zh/special-disc/story-dialogue.json', 'corpus/zh/special-disc/challenge-dialogue.json',
              'corpus/zh/special-disc/frame-text.json', 'corpus/zh/special-disc/squad-names.json',
              'corpus/zh/story-dialogue/', 'corpus/zh/story-speakers.json', 'corpus/zh/story-conditions.json'),
    'srvc': ('corpus/zh/battle/srvc-lines.json', 'corpus/zh/special-disc/battle-lines.json'),
    'frame': ('corpus/zh/special-disc/frame-text.json', 'corpus/zh/menu/stage-names.json'),
    'image-labels': ('corpus/zh/special-disc/frame-text.json',),
}
CODE_ROOTS = ('tools/special_disc/', 'tools/srwz/', 'tools/native/srwz-codec-rs/',
              'tools/build_rust_compressor.py', 'vendor/upstream-python/')


def component_inputs(rows: list[dict], name: str) -> list[dict]:
    """Exact inventory, including additions/removals; ignore unrelated main-game corpora/tools."""
    def selected(path):
        if path.startswith(('config/', 'work/')) or path.startswith(CODE_ROOTS):
            return True
        return any(path.startswith(p) if p.endswith('/') else path == p for p in CORPORA[name])
    return [dict(path=r['path'], size=r['size'], sha256=r['sha256'])
            for r in sorted(rows, key=lambda r: r['path']) if selected(r['path'])]


def file_lock(path: Path, root: Path) -> dict:
    return dict(path=path.relative_to(root).as_posix(), size=path.stat().st_size, sha256=sha256_file(path))


def matches(path: Path, lock: dict) -> bool:
    return (path.is_file() and not path.is_symlink() and path.stat().st_size == lock['size']
            and sha256_file(path) == lock['sha256'])


def seed_components(source: Path, manifest: Path, expected_sha: str, target: Path) -> bool:
    """Carry only component files sealed by a successful prior independent readback.

    A stale, absent or damaged cache is optional: fall back to writer execution.
    No ISO or authoritative input is copied from the previous build.
    """
    try:
        if sha256_file(manifest) != expected_sha:
            return False
        report = load_json(manifest)
        cache = report.get('incremental', {})
        if (report.get('status') != 'all_bound_text_reread_from_final_iso_runtime_pending'
                or cache.get('schema_version') != SCHEMA or set(cache.get('components', {})) != set(COMPONENTS)):
            return False
        independent = report['independent_readback']
        proof_path = project_path(source, independent['path'], 'work/build/special-disc/full-text')
        if sha256_file(proof_path) != independent['sha256']:
            return False
        proof = load_json(proof_path)
        if (proof['status'] != 'all_bound_text_reread_from_final_iso'
                or proof['iso'] != report['iso'] or proof.get('component_hashes_verified') is not True):
            return False
        roots = {project_path(source, p, 'work/build/special-disc/full-text').parent.parent
                 for p in report['components']}
        if len(roots) != 1:
            return False
        run = roots.pop()
        for name in COMPONENTS:
            row = cache['components'][name]
            report_path = (run / name / 'report.json').relative_to(source).as_posix()
            if row['report']['sha256'] != report['components'].get(report_path):
                return False
            for lock in [row['report'], *row['files']]:
                path = project_path(run, lock['path'], name)
                if matches(path, lock):
                    copy_file(path, project_path(target, lock['path'], name))
        target.mkdir(parents=True, exist_ok=True)
        (target / 'cache.json').write_bytes(json_bytes(cache))
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


class ComponentCache:
    def __init__(self, root: Path, work: Path, *, force: bool = False, rows=None):
        self.root, self.work, self.force = root, work, force
        self.verify_inputs = rows is None
        self.rows = source_inventory(root, locked_sp_inputs(root)) if rows is None else rows
        self.directory = root / CACHE_PATH
        self.previous = {}
        if not force:
            try:
                data = load_json(self.directory / 'cache.json')
                if data.get('schema_version') == SCHEMA and isinstance(data.get('components'), dict):
                    self.previous = data['components']
            except (OSError, ValueError, KeyError):
                pass
        self.records = {}

    def fingerprint(self, name: str) -> tuple[str, list[dict], dict]:
        inputs = component_inputs(self.rows, name)
        dependencies = {}
        if name == 'stage':
            dependencies['system_stage_sha256'] = sha256_file(self.work / 'system/DATA/STAGE.BIN.overlay')
        digest = hashlib.sha256(json_bytes(dict(schema_version=SCHEMA, component=name,
                                                inputs=inputs, dependencies=dependencies))).hexdigest()
        return digest, inputs, dependencies

    def run(self, name: str, builder) -> None:
        fingerprint, inputs, dependencies = self.fingerprint(name)
        previous = self.previous.get(name, {})
        if not isinstance(previous, dict):
            previous = {}
        reason = 'forced rebuild' if self.force else 'input fingerprint changed or no verified cache'
        reused = False
        if not self.force and previous.get('fingerprint') == fingerprint:
            try:
                locks = [previous['report'], *previous['files']]
                report_path = project_path(self.directory, previous['report']['path'], name)
                if not all(matches(project_path(self.directory, r['path'], name), r) for r in locks):
                    raise ValueError('cached component bytes changed')
                report = load_json(report_path)
                expected_files = {f'{name}/{p}': digest for p, digest in report['files'].items()}
                if (previous['report']['path'] != f'{name}/report.json'
                        or not expected_files or len(expected_files) != len(previous['files'])
                        or expected_files != {r['path']: r['sha256'] for r in previous['files']}):
                    raise ValueError('cached output inventory changed')
                for row in locks:
                    destination = project_path(self.work, row['path'], name)
                    copy_file(project_path(self.directory, row['path'], name), destination)
                    if not matches(destination, row):
                        raise ValueError('component copy changed')
                if name == 'stage':
                    # These are provenance paths, not part of produced game bytes.
                    report['baseline']['path'] = str(self.work / 'system')
                    report['proposal']['path'] = str(self.root / 'work/build/special-disc/text-candidate/font/proposal.json')
                    (self.work / name / 'report.json').write_bytes(json_bytes(report))
                reused, reason = True, 'matching dependencies and verified component bytes'
            except (OSError, ValueError, KeyError, TypeError) as error:
                reason = f'cache miss: {error}'
        if not reused:
            builder()
        report_path = self.work / name / 'report.json'
        report = load_json(report_path)
        expected_status = 'static_component_verified_runtime_pending' if name == 'stage' else 'static_verified_runtime_pending'
        # system and SRVC have their own status vocabulary; assembly checks their
        # corpus coverage and each output hash before final independent readback.
        if name in ('stage', 'frame', 'image-labels') and report.get('status') != expected_status:
            raise ValueError(f'{name}: component did not pass validation')
        files = []
        for path, digest in report['files'].items():
            member = project_path(self.work / name, path)
            row = file_lock(member, self.work)
            if row['sha256'] != digest:
                raise ValueError(f'{name}: output hash differs from component report')
            files.append(row)
        if not files:
            raise ValueError(f'{name}: component has no output files')
        self.records[name] = dict(fingerprint=fingerprint, inputs=inputs, dependencies=dependencies,
                                 mode='reused' if reused else 'rebuilt', reason=reason,
                                 report=file_lock(report_path, self.work), files=files)
        print(f'[sp cache] {name}: {self.records[name]["mode"]} ({reason})', flush=True)

    def receipt(self) -> dict:
        if set(self.records) != set(COMPONENTS):
            raise ValueError('incomplete SP component cache generation')
        if self.verify_inputs:
            current = source_inventory(self.root, locked_sp_inputs(self.root))
            for name in COMPONENTS:
                if component_inputs(current, name) != self.records[name]['inputs']:
                    raise ValueError(f'{name}: inputs changed during component build')
        return dict(schema_version=SCHEMA, components=self.records)
