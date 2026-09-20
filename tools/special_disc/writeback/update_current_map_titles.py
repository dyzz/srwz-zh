"""Atomically fix inherited world-map titles in the sole SP current ISO."""
from pathlib import Path
import copy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import load, file_sha, read_member, write_json, verify_iso_ranges
from special_disc.source import CURRENT_ISO
from special_disc.writeback.world_map_titles import (apply_world_map_titles,
    verify_world_map_titles, inputs, MEMBER, require, sha)
from special_disc.writeback.install_font import sp_offsets
from srwz.iso9660 import member_map, scan_iso9660

OUTPUT = ROOT/'work/verification/sp-current-world-map-titles'


def main():
    manifest_path = CURRENT_ISO.with_suffix('.json')
    manifest = load(manifest_path)
    require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO identity drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    exe = read_member(CURRENT_ISO, members, 'SLPS_259.20')
    before = read_member(CURRENT_ISO, members, MEMBER)
    require(sha(before) == manifest['files'][MEMBER], 'current map member identity drift')
    result, titles = apply_world_map_titles(before, exe)
    if result == before:
        print('all inherited SP map titles already match the frozen Chinese bitmaps')
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT/'previous-manifest.json', manifest)
    temporary = CURRENT_ISO.with_suffix('.tmp.iso')
    require(not temporary.exists(), 'another current ISO update is in progress')
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        at = members[MEMBER].extent_lba*2048
        with temporary.open('r+b') as stream:
            stream.seek(at); stream.write(result)
        after = member_map(scan_iso9660(temporary))
        require({n:(m.extent_lba,m.size) for n,m in members.items()} ==
                {n:(m.extent_lba,m.size) for n,m in after.items()}, 'ISO layout changed')
        actual = read_member(temporary, after, MEMBER)
        require(actual == result, 'world-map ISO member readback failed')
        verify_world_map_titles(actual, exe)
        config = inputs(); offsets = sp_offsets(exe, config['table_offset'], len(before))
        protected = verify_iso_ranges(CURRENT_ISO, temporary,
            [(at+offsets[r['chunk']], at+offsets[r['chunk']+1]) for r in config['bindings']])
        receipt = dict(status='world_map_titles_static_verified_runtime_pending',
            previous_iso=manifest['iso'], world_map_titles=titles,
            protected_iso_ranges=protected, member_sha256=sha(result),
            iso=dict(path=str(CURRENT_ISO.relative_to(ROOT)), size=temporary.stat().st_size,
                     sha256=file_sha(temporary)))
        updated = copy.deepcopy(manifest)
        updated.update(iso=receipt['iso'], status=receipt['status'],
                       world_map_titles=titles, runtime='pending after font and map-title updates')
        updated['files'][MEMBER] = sha(result)
        updated['world_map_title_update'] = dict(receipt=str((OUTPUT/'readback.json').relative_to(ROOT)),
            previous_manifest=str((OUTPUT/'previous-manifest.json').relative_to(ROOT)))
        require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO changed during update')
        temporary.replace(CURRENT_ISO)
        write_json(manifest_path, updated)
        write_json(OUTPUT/'readback.json', receipt)
        print(receipt['iso'])
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
