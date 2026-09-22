"""Seed private Original text updates only from a same-tooling validated run."""
import shutil

from .edition import load_json, project_path
from .release_inputs import copy_file, seed_original_caches, sha256_file


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
    old = {r['path']: r for r in load_json(old_snapshot)['files']}
    new = {r['path']: r for r in snapshot.files}
    # The generated locks can be carried forward only if their source configs,
    # tools, fonts and baseline inputs did not change. Corpus edits are rebound
    # by the normal component pipeline, including per-STAGE dependency checks.
    if any(old.get(p) != new.get(p) and not p.startswith('corpus/') for p in old.keys() | new.keys()):
        return False
    source = project_path(context.root, previous['workspace'], 'build/editions')
    if source == context.project_root:
        # materialize() has restored source inputs; overlay verified generated
        # metadata below, without copying a directory onto itself.
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
    return True
