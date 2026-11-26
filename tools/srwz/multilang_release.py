"""Freeze and verify schema 7 regional candidate, assembly and widescreen evidence."""
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from .current_iso import verify_regional_skip
from .edition import EditionError, json_bytes
from .release_inputs import copy_file, sha256_file

REGIONS = {'sc': '', 'tw': 'zh-hant-tw', 'hk': 'zh-hant-hk'}
EDITIONS = ('original', 'best', 'sp')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def identity(lock):
    return {key: lock[key] for key in ('size', 'sha256')}


def file_lock(root, path):
    return {'path': str(path.relative_to(root)), 'size': path.stat().st_size, 'sha256': sha256_file(path)}


def require(condition, message):
    if not condition:
        raise EditionError(message)


def freeze(root, version, directory, xdelta, *, check_only=False):
    from verify_editions import verify_batch
    from build_editions import edition_lock
    require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'invalid version')
    tag = 'v' + version
    frozen = root / 'build/iso' / tag
    evidence = root / 'manifests/releases' / tag
    config_path = root / 'config/release' / (tag + '.json')
    with edition_lock(root / 'work/cache/editions/multilang/build.lock'), TemporaryDirectory(dir=frozen.parent) as scratch:
        require(not any(p.exists() for p in (frozen, evidence, config_path)), 'release already exists')
        images = Path(scratch) / 'images'
        proofs = Path(scratch) / 'proofs'
        images.mkdir()
        proofs.mkdir()

        def save(name, data):
            path = proofs / name
            path.write_bytes(data.read_bytes() if isinstance(data, Path) else json_bytes(data))
            return {'path': str((evidence / name).relative_to(root)), **identity(file_lock(root, path))}

        validation = {'status': 'multilang_widescreen_readback_passed', 'runtime': 'not_tested',
                      'editions': {}, 'batches': {}}
        for region, lang in REGIONS.items():
            batches = {}
            for edition in EDITIONS:
                suffix = '-' + lang if lang else ''
                result = read(root / f'manifests/editions/{edition}/candidate{suffix}.json')
                group = 'sp' if edition == 'sp' else 'original-best'
                manifest = root / 'work/editions' / result['input_digest'] / f'{group}-candidate{suffix}.json'
                if group not in batches:
                    batch = read(manifest)
                    verification = verify_batch(root, manifest)
                    snapshot = (root / batch['input_snapshot']).parent / 'project/config/assets/title-menu-zh.json'
                    require(batch.get('version') == read(snapshot)['version_badge']['text'] == tag
                            and batch.get('language', '') == lang, 'candidate badge or language mismatch')
                    batches[group] = batch
                    validation['batches'].setdefault(region, {})[group] = save(
                        f'{region}-{group}-batch.json', {'batch': batch, 'verification': verification})
                require(result in batches[group]['results'], 'candidate changed since batch verification')
                proof = root / result['readback']['path']
                require(sha256_file(proof) == result['readback']['sha256'], 'candidate readback changed')
                item = validation['editions'].setdefault(edition, {'regions': {}})
                record = {'readback': save(f'{edition}-{region}-readback.json', proof)}
                if edition == 'sp':
                    independent = read(proof)['independent_readback']
                    path = root / result['workspace'] / independent['path']
                    require(sha256_file(path) == independent['sha256'], 'SP independent readback changed')
                    record['independent'] = save(f'sp-{region}-independent.json', path)
                item['regions'][region] = record

        config = {'schema_version': 7, 'tag': tag, 'version': version, 'channel': 'stable', 'skip': 'built_in',
                  'validation': str((evidence / 'validation.json').relative_to(root)), 'editions': {},
                  'xdelta': xdelta, 'output': {'directory': f'build/release/{tag}'}, 'known_limitations': []}
        for edition in EDITIONS:
            assembly_path = directory / f'multilang-{edition}.receipt.json'
            wide_path = directory / f'multilang-{edition}-wide.receipt.json'
            item = validation['editions'][edition]
            assembly, wide = read(assembly_path), read(wide_path)
            middle = directory / f'multilang-{edition}.iso'
            target = images / f'srwz-zh-{tag}-{edition}.iso'
            copy_file(directory / f'multilang-{edition}-wide.iso', target)
            require(assembly['output'] == wide['input'] == identity(file_lock(root, middle)),
                    'wide build does not derive from assembled disc')
            require(assembly['edition'] == wide['edition'] == edition and wide['output'] == identity(file_lock(root, target)),
                    'final disc differs from widescreen receipt')
            for region in REGIONS:
                group = 'sp' if edition == 'sp' else 'original-best'
                batch = read(proofs / Path(validation['batches'][region][group]['path']).name)['batch']
                result = next(r for r in batch['results'] if r['edition_id'] == edition)
                require(assembly['inputs'][region] == identity(result['output']), f'{edition} {region}: assembly input mismatch')
            item['assembly'] = save(f'{edition}-assembly.json', assembly)
            item['wide'] = save(f'{edition}-wide.json', wide)
            item['skip'] = save(f'{edition}-skip.json', verify_regional_skip(target, root, edition, assembly))
            profile = f'config/editions/{edition}/edition.json'
            config['editions'][edition] = {'edition_config': profile, 'source_iso': read(root / profile)['source_iso'],
                'target_iso': {'path': str((frozen / target.name).relative_to(root)), **wide['output']},
                'patch_filename': f'srwz-zh-{tag}-{edition}.xdelta'}
        validation['input_digest'] = hashlib.sha256(json_bytes(validation['batches'])).hexdigest()
        save('validation.json', validation)
        config['evidence'] = [str(config_path.relative_to(root)), f'docs/RELEASE_NOTES_V{version}.md',
                              *[str((evidence / p.name).relative_to(root)) for p in sorted(proofs.iterdir())]]
        verify(root, config, validation, staged_images=images, staged_proofs=proofs)
        if check_only:
            return validation
        images.rename(frozen)
        try:
            proofs.rename(evidence)
            try:
                config_temp = Path(scratch) / 'config.json'
                config_temp.write_bytes(json_bytes(config))
                config_temp.rename(config_path)
            except BaseException:
                evidence.rename(proofs)
                raise
        except BaseException:
            frozen.rename(images)
            raise
    return config_path


def verify_wide(target, edition, wide):
    from zh_hant.assemble_dual import Disc, Elf
    from zh_hant.editions import EDITIONS as profiles
    disc = Disc(target)
    profile = profiles[edition]
    elf = Elf(disc.read(profile.exe))
    words = wide['elf_words']
    title_address = hex(profile.title_site[0])
    require(title_address in words and words[title_address] >> 26 == 3,
            'widescreen title hook missing')
    require(all(elf.word(int(address, 16)) == value for address, value in words.items()),
            'widescreen ELF words differ')
    flag = wide['wide_enabled']
    require(elf.word(flag['address']) == flag['default'] == 0, 'widescreen default differs')
    effect = disc.read('EFF/VEFF2DX.BIN')
    require(wide['members'].get('EFF/VEFF2DX.BIN') ==
            {'size': len(effect), 'sha256': hashlib.sha256(effect).hexdigest()},
            'widescreen effect member differs')


def verify(root, config, validation, *, staged_images=None, staged_proofs=None):
    tag = config['tag']
    prefix = f'manifests/releases/{tag}/'
    require(re.fullmatch(r'v\d+\.\d+\.\d+', tag) and config['validation'] == prefix + 'validation.json',
            'invalid frozen evidence location')
    require(validation['status'] == 'multilang_widescreen_readback_passed' and config['skip'] == 'built_in',
            'incomplete multilang release')
    require(set(validation['batches']) == set(REGIONS) and set(validation['editions']) == set(EDITIONS)
            and set(config.get('editions', {})) == set(EDITIONS),
            'incomplete edition or region inventory')

    def checked(lock, name):
        require(lock['path'] == prefix + name, f'unexpected evidence path for {name}')
        path = staged_proofs / name if staged_proofs else root / lock['path']
        require(identity(lock) == identity(file_lock(root, path)), f'changed evidence: {name}')
        return read(path)

    if validation.get('runtime') == 'armsx2_frozen_discs_verified':
        runtime = checked(validation['runtime_evidence'], 'runtime.json')
        require(runtime['runner'] == 'ARMSX2 headless' and set(runtime['editions']) == set(EDITIONS),
                'incomplete runtime evidence')
        for edition, result in runtime['editions'].items():
            require(result['iso_sha256'] == config['editions'][edition]['target_iso']['sha256']
                    and set(result['languages']) == set(REGIONS), 'runtime evidence uses another disc or region')

    require(validation['input_digest'] == hashlib.sha256(json_bytes(validation['batches'])).hexdigest(),
            'regional batch identities changed')
    for edition, item in config['editions'].items():
        profile = f'config/editions/{edition}/edition.json'
        name = f'srwz-zh-{tag}-{edition}'
        require(item['edition_config'] == profile and read(root / profile)['source_iso'] == item['source_iso']
                and item['patch_filename'] == name + '.xdelta', 'wrong edition contract')
        target = root / 'build/iso' / tag / (name + '.iso')
        require(item['target_iso']['path'] == str(target.relative_to(root)), 'unexpected frozen disc path')
        if staged_images:
            target = staged_images / target.name
        require(identity(file_lock(root, target)) == identity(item['target_iso']), 'frozen disc identity mismatch')
        entry = validation['editions'][edition]
        assembly = checked(entry['assembly'], f'{edition}-assembly.json')
        wide = checked(entry['wide'], f'{edition}-wide.json')
        require(assembly['languages'] == 3 and set(assembly['inputs']) == set(REGIONS)
                and assembly['edition'] == wide['edition'] == edition and assembly['output'] == wide['input']
                and wide['output'] == identity(item['target_iso']), 'release disc chain mismatch')
        verify_wide(target, edition, wide)
        require(checked(entry['skip'], f'{edition}-skip.json') == verify_regional_skip(target, root, edition, assembly),
                'regional skip readback differs from frozen disc')
        for region, lang in REGIONS.items():
            group = 'sp' if edition == 'sp' else 'original-best'
            evidence = checked(validation['batches'][region][group], f'{region}-{group}-batch.json')
            batch, verification = evidence['batch'], evidence['verification']
            require(batch.get('language', '') == lang and batch['version'] == tag
                    and verification['status'] == 'edition_batch_receipt_integrity_passed'
                    and edition in verification['verified_editions'] and verification['input_digest'] == batch['input_digest'],
                    'invalid regional candidate verification')
            result, = (row for row in batch['results'] if row['edition_id'] == edition)
            regional = entry['regions'][region]
            proof = checked(regional['readback'], f'{edition}-{region}-readback.json')
            require(result['input_digest'] == batch['input_digest'] and assembly['inputs'][region] == identity(result['output'])
                    and regional['readback']['sha256'] == result['readback']['sha256'], 'regional proof binding mismatch')
            if edition == 'sp':
                independent = checked(regional['independent'], f'sp-{region}-independent.json')
                require(regional['independent']['sha256'] == proof['independent_readback']['sha256']
                        and independent['component_hashes_verified'] and independent['iso']['sha256'] == proof['iso']['sha256'],
                        'SP independent proof binding mismatch')
