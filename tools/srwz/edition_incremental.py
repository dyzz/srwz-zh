"""Seed private Original workspaces from the previous validated run.

Only files that can change produced component bytes block the seed: the
component build definitions (see ``COMPONENT_BUILD_DEFINITION_ROOTS``). Corpus
edits are rebound by the component pipeline's own per-consumer checks, and a
config or manifest that now equals exactly what the previous validated run
wrote (its refreshed locks synced back into the repository) is the same input
that run already validated. Edits to orchestration, ISO building, verifiers or
documentation never invalidate component caches.
"""
import shutil

from .build_fingerprints import is_component_build_definition
from .edition import load_json, project_path
from .release_inputs import copy_file, is_build_input, seed_original_caches, sha256_file

ISO_BASELINE_FILES = (
    'build/iso/zh-release-full-story/current-original.iso',
    'build/iso/zh-release-full-story/iso-validation-current.json',
    'build/iso/zh-release-full-story/iso-validation-current.incremental.json',
)


def component_inputs_changed(old: dict, new: dict, produced_root) -> bool:
    """True when a component build definition differs beyond what the previous run produced."""
    for path in old.keys() | new.keys():
        if old.get(path) == new.get(path) or path.startswith('corpus/'):
            continue
        if not is_build_input(path) or not is_component_build_definition(path):
            continue
        row = new.get(path)
        if row is not None and path.startswith(('config/', 'manifests/')):
            produced = produced_root / path
            if (produced.is_file() and row.get('size', produced.stat().st_size) == produced.stat().st_size
                    and sha256_file(produced) == row['sha256']):
                continue
        return True
    return False


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
    if component_inputs_changed(old, new, source):
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
    # The previous validated image lets build_iso --incremental clone it and
    # rewrite only changed members; build_iso rebinds it by content hash.
    if all((source / p).is_file() for p in ISO_BASELINE_FILES):
        for p in ISO_BASELINE_FILES:
            copy_file(source / p, context.project_root / p)
    return True
