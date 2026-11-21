"""Seed private Original workspaces from the previous validated run.

Only files that can change produced component bytes block the seed: the
component build definitions (see ``COMPONENT_BUILD_DEFINITION_ROOTS``). Corpus
edits are rebound by the component pipeline's own per-consumer checks, and a
config or manifest that now equals exactly what the previous validated run
wrote (its refreshed locks synced back into the repository) is the same input
that run already validated. Edits to orchestration, ISO building, verifiers or
documentation never invalidate component caches.
"""
import json
import shutil

from .build_language import ASKED, ASKED_COMPLETE, LITERALS
from .build_fingerprints import is_component_build_definition
from .edition import load_json, project_path
from .release_inputs import copy_file, is_build_input, seed_original_caches, sha256_file

ISO_BASELINE_FILES = (
    'build/iso/zh-release-full-story/current-original.iso',
    'build/iso/zh-release-full-story/iso-validation-current.json',
    'build/iso/zh-release-full-story/iso-validation-current.incremental.json',
)


def literals_answers_unchanged(source, project_root, old_row) -> bool:
    """A Traditional build's dictionary (config/zh-hant/readback-literals.json) is made from every corpus string,
    so any edited line changes the file. The builders ask it for particular entries, and every process notes
    the ones it asked (srwz.build_language). True when every entry asked since the chain's last complete
    component build answers the same in the new dictionary as in the previous run's."""
    asked = source / ASKED
    old_path, new_path = source / LITERALS, project_root / LITERALS
    try:
        if not (asked / ASKED_COMPLETE).is_file() or sha256_file(old_path) != old_row['sha256']:
            return False
        old, new = load_json(old_path), load_json(new_path)
        if ({key: value for key, value in old.items() if key not in ('literals', 'characters', 'ambiguous')}
                != {key: value for key, value in new.items() if key not in ('literals', 'characters', 'ambiguous')}):
            return False
        for notes in asked.glob('*.jsonl'):
            with notes.open(encoding='utf-8') as lines:
                for line in dict.fromkeys(lines):
                    section, key = json.loads(line)
                    if old.get(section, {}).get(key) != new.get(section, {}).get(key):
                        return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def component_inputs_changed(old: dict, new: dict, produced_root, project_root=None) -> bool:
    """True when a component build definition differs beyond what the previous run produced."""
    return changed_component_input(old, new, produced_root, project_root) is not None


def changed_component_input(old: dict, new: dict, produced_root, project_root=None):
    """The first component build definition that differs beyond what the previous run produced, or None."""
    for path in sorted(old.keys() | new.keys()):
        if old.get(path) == new.get(path) or path.startswith('corpus/'):
            continue
        if (path == LITERALS.as_posix() and project_root is not None and old.get(path) and new.get(path)
                and literals_answers_unchanged(produced_root, project_root, old[path])):
            continue
        if not is_build_input(path) or not is_component_build_definition(path):
            continue
        row = new.get(path)
        if row is not None and path.startswith(('config/', 'manifests/')):
            produced = produced_root / path
            if (produced.is_file() and row.get('size', produced.stat().st_size) == produced.stat().st_size
                    and sha256_file(produced) == row['sha256']):
                continue
        return path
    return None


def seed_text_update(context, snapshot):
    if not context.receipt.is_file():
        return False
    previous = load_json(context.receipt)
    if (previous.get('status') != 'edition_iso_static_validated_runtime_pending'
            or previous.get('edition_contract_sha256') != context.profile.contract_sha256):
        return False
    old_snapshot = project_path(context.root,
        f"work/build/shared/{previous['input_digest']}/inputs.json", 'work/build/shared')
    if not old_snapshot.is_file():
        return False
    source = project_path(context.root, previous['workspace'], 'build/editions')
    if source == context.project_root:
        # materialize() has restored source inputs; overlay verified generated
        # metadata below, without copying a directory onto itself.
        return False
    old = {r['path']: r for r in load_json(old_snapshot)['files']}
    new = {r['path']: r for r in snapshot.files}
    blocking = changed_component_input(old, new, source, context.project_root)
    if blocking is not None:
        print(f"[original] component caches not carried: {blocking} changed", flush=True)
        # The component caches stay behind, the image does not have to: build_iso --incremental takes a
        # previous image only when its builder, layout policy, source disc, report and the image itself hash
        # to what that run recorded, and rewrites exactly the members whose hashes differ now.
        carry_iso_baseline(source, context.project_root)
        return False
    proof = project_path(context.root, previous['readback']['path'], previous['workspace'])
    cache = source / 'work/cache/editions/original/font-chain.json'
    if not proof.is_file() or sha256_file(proof) != previous['readback']['sha256'] or not cache.is_file():
        return False
    cached = load_json(cache)
    metadata = []
    for row in cached['files']:
        p = row['path']
        if not p.startswith(('config/', 'manifests/')) or p not in new:
            continue
        # The ISO builder refreshes its output locks after the component cache
        # is sealed. It is not component metadata; keep the captured source
        # config and let build_iso bind it to the new validated components.
        if p.startswith('config/iso/'):
            continue
        path = project_path(source, p)
        if not path.is_file() or path.stat().st_size != row['size'] or sha256_file(path) != row['sha256']:
            return False
        metadata.append(p)
    seed_original_caches(source, context.project_root, overwrite_cache=True)
    if (source / 'work/cache').is_dir():
        shutil.copytree(source / 'work/cache', context.project_root / 'work/cache',
                        copy_function=copy_file, dirs_exist_ok=True)
    for p in metadata:
        copy_file(source / p, context.project_root / p)
    _merge_asked_notes(context.project_root / ASKED)
    carry_iso_baseline(source, context.project_root)
    return True


def _merge_asked_notes(directory) -> None:
    """The notes carried from the previous run stand for every process of the chain so far: one file."""
    files = sorted(directory.glob('*.jsonl')) if directory.is_dir() else []
    if len(files) < 2:
        return
    lines = {}
    for path in files:
        with path.open(encoding='utf-8') as stream:
            lines.update(dict.fromkeys(stream))
    pending = directory / '.merged.tmp'
    pending.write_text(''.join(lines), encoding='utf-8')
    for path in files:
        path.unlink()
    pending.rename(directory / 'carried.jsonl')


def carry_iso_baseline(source, project_root) -> bool:
    """The previous validated image lets build_iso --incremental clone it and rewrite only changed members;
    build_iso rebinds it by content hash."""
    if not all((source / p).is_file() for p in ISO_BASELINE_FILES):
        return False
    for p in ISO_BASELINE_FILES:
        (project_root / p).parent.mkdir(parents=True, exist_ok=True)
        copy_file(source / p, project_root / p)
    return True
