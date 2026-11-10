"""Install and independently read back the native-entry proportional renderer.

Only the executable extent changes. The receipt binds the source ISO, font
metrics, exact regenerated ELF and every byte outside that executable.
"""
from hashlib import sha256
import json
from pathlib import Path
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file
from .tag_free_integrated import install
from .ui_battle_select import CONFIG as BATTLE_SELECT, SP_CONFIG as SP_BATTLE_SELECT
from .ui_battle_select import apply_atlas as apply_select_atlas, apply_executable

EXECUTABLES = {'original': 'SLPS_258.87', 'best': 'SLPS_732.70', 'sp': 'SLPS_259.20'}


def _expected(root, edition, source):
    registry_bytes = (root / 'shared/text-layout/proportional-metrics.mjs').read_bytes()
    registry = json.loads(registry_bytes.decode().split(' = ', 1)[1].rstrip(';\n'))
    members = member_map(scan_iso9660(source))
    member = members[EXECUTABLES[edition]]
    start = member.extent_lba * 2048
    with source.open('rb') as stream:
        stream.seek(start)
        original = stream.read(member.size)
    patched, payload = install(original, registry, edition, scene_dispatch=True)
    select_path = root / (SP_BATTLE_SELECT if edition == "sp" else BATTLE_SELECT)
    if select_path.is_file():
        raw = select_path.read_bytes()
        contract = json.loads(raw)
        atlas = members["KURODATA/KVMDATA.BIN"]
        with source.open("rb") as stream:
            stream.seek(atlas.extent_lba * 2048)
            apply_select_atlas(stream.read(atlas.size), contract, strict=True)
        patched = apply_executable(patched, contract, edition)
        payload["resultSha256"] = sha256(patched).hexdigest()
        payload["battle_select_titles"] = {
            "config_sha256": sha256(raw).hexdigest(), "labels": contract["labels"],
        }
    if len(patched) != member.size:
        raise ValueError('Typography executable size changed')
    return members, member, patched, payload, sha256(registry_bytes).hexdigest()


def verify_iso(root: Path, edition: str, source: Path, output: Path, receipt=None):
    members, member, expected, payload, registry_hash = _expected(root, edition, source)
    if member_map(scan_iso9660(output)) != members:
        raise ValueError('Typography changed ISO member records')
    start, end = member.extent_lba * 2048, member.extent_lba * 2048 + member.size
    before, after, compared = sha256(), sha256(), 0
    with source.open('rb') as src, output.open('rb') as dst:
        pos = 0
        while chunk := src.read(4 * 1024 * 1024):
            actual = dst.read(len(chunk))
            if len(actual) != len(chunk):
                raise ValueError('Typography ISO truncated')
            before.update(chunk)
            after.update(actual)
            for lo, hi in [(pos, min(pos + len(chunk), start)),
                           (max(pos, end), pos + len(chunk))]:
                if hi > lo:
                    if chunk[lo-pos:hi-pos] != actual[lo-pos:hi-pos]:
                        raise ValueError('Typography changed bytes outside executable')
                    compared += hi - lo
            lo, hi = max(pos, start), min(pos + len(chunk), end)
            if hi > lo and actual[lo-pos:hi-pos] != expected[lo-start:hi-start]:
                raise ValueError('Typography executable readback differs from regenerated patch')
            pos += len(chunk)
        if dst.read(1):
            raise ValueError('Typography ISO grew')
    result = dict(schema_version=1, edition=edition, source_sha256=before.hexdigest(),
                  output_sha256=after.hexdigest(), size=pos, metrics_sha256=registry_hash,
                  executable_sha256=sha256(expected).hexdigest(), member=EXECUTABLES[edition],
                  member_lba=member.extent_lba, member_size=member.size,
                  outside_executable_bytes_compared=compared, payload=payload,
                  runtime='not_tested')
    if receipt is not None and result != receipt:
        raise ValueError('Typography receipt does not match actual ISO and renderer inputs')
    return result


def seal_iso(root: Path, edition: str, source: Path, output: Path):
    root, source, output = root.resolve(), source.resolve(), output.resolve()
    iso_root = root / 'build/iso'
    if source == output or not source.is_relative_to(iso_root) or not output.is_relative_to(iso_root):
        raise ValueError('Typography requires distinct project-local build/iso paths')
    if output.exists():
        raise ValueError('Typography output already exists')
    _, member, patched, _, _ = _expected(root, edition, source)
    output.parent.mkdir(parents=True, exist_ok=True)
    copy_file(source, output)
    try:
        with output.open('r+b') as stream:
            stream.seek(member.extent_lba * 2048)
            stream.write(patched)
        return verify_iso(root, edition, source, output)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
