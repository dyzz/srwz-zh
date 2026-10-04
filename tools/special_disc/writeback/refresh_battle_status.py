"""Refresh only the ten frozen status texts in the verified current SP ISO."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.source import CURRENT_ISO
from special_disc.writeback.battle_status import apply_status_labels, verify_status_labels, MEMBER
from special_disc.writeback.battle_prompts import verify_prompt_labels
from special_disc.writeback.battle_titles import verify_title_labels
from srwz.iso9660 import scan_iso9660, member_map
from srwz.file_identity import publish_verified
from special_disc.writeback.build_text_candidate import verify_iso_ranges


def sha_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    work = args.evidence.resolve()
    work.mkdir(parents=True, exist_ok=True)
    iso = CURRENT_ISO
    sidecar = iso.with_suffix('.json')
    original_manifest = sidecar.read_bytes()
    manifest = json.loads(original_manifest)
    source_sha = sha_file(iso)
    if source_sha != manifest['iso']['sha256']:
        raise ValueError('current SP ISO identity drift')
    members = member_map(scan_iso9660(iso))
    member = members[MEMBER]
    at = member.extent_lba * 2048
    with iso.open('rb') as stream:
        stream.seek(at)
        before = stream.read(member.size)
    after, status = apply_status_labels(before)
    if after == before:
        print('Current SP status texts already match the frozen snapshot')
        return
    previous = work / 'previous-status.iso'
    if previous.exists():
        raise ValueError('status evidence directory already contains an ISO revision')
    subprocess.run(['cp', '-c', str(iso), str(previous)], check=True)
    temporary = work / 'published-status.iso'
    subprocess.run(['cp', '-c', str(iso), str(temporary)], check=True)
    with temporary.open('r+b') as stream:
        stream.seek(at)
        stream.write(after)
    updated = member_map(scan_iso9660(temporary))
    if {k:(v.extent_lba,v.size) for k,v in members.items()} != {k:(v.extent_lba,v.size) for k,v in updated.items()}:
        raise ValueError('status update moved ISO members')
    with temporary.open('rb') as stream:
        stream.seek(at)
        reread = stream.read(member.size)
    if reread != after:
        raise ValueError('status ISO member readback drift')
    verified = verify_status_labels(reread)
    protected = verify_iso_ranges(previous, temporary, [(at+290000, at+355536)])
    output_sha = sha_file(temporary)
    receipt = dict(status='status_cells_reread_other_iso_bytes_preserved_runtime_pending',
                   before_iso_sha256=source_sha, after_iso_sha256=output_sha,
                   previous_iso=str(previous.relative_to(ROOT)),
                   status_labels=verified, migration=status, protected_iso_ranges=protected,
                   inherited_text_proof=manifest.get('independent_readback'),
                   scope='Only 10 status text rectangles; original CLUT, arrows, other labels and all non-atlas ISO bytes preserved')
    receipt_path = work / 'production-readback.json'
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    manifest.setdefault('inherited_independent_readbacks', []).append(manifest['independent_readback'])
    manifest['iso']['sha256'] = output_sha
    manifest['files'][MEMBER] = hashlib.sha256(after).hexdigest()
    manifest['battle_status_labels'] = status
    if 'battle_prompt_labels' in manifest:
        manifest['battle_prompt_labels'] = verify_prompt_labels(after)
    if 'battle_title_labels' in manifest:
        manifest['battle_title_labels'] = verify_title_labels(after)
    manifest['coverage']['battle_status_labels'] = 10
    manifest['independent_readback'] = dict(path=str(receipt_path.relative_to(ROOT)),sha256=sha_file(receipt_path))
    manifest.setdefault('asset_updates', []).append(manifest['independent_readback'])
    manifest['runtime'] = 'pending'
    manifest['status'] = 'status_labels_reread_inherited_text_byte_exact_runtime_pending'
    updated_manifest = temporary.with_suffix('.json')
    updated_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    if sha_file(iso) != source_sha or sidecar.read_bytes() != original_manifest:
        raise ValueError('current SP ISO or manifest changed during status update')
    publish_verified(temporary, iso, output_sha)
    updated_manifest.replace(sidecar)
    print('Current SP ISO updated: 10 status texts only; '+output_sha)


if __name__ == '__main__':
    main()
