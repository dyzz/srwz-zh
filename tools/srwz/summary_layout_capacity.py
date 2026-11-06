"""Fixed MTV_PROS allocations constrain layout before any corpus writeback."""
from pathlib import Path
import hashlib
import json

from .codec import decode_production
from .iso9660 import member_map, scan_iso9660
from .iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from .summary import parse_summary
from .text import (encode_text, load_text_table, normalize_original_fullwidth_ascii,
                   original_fullwidth_ascii_overrides)
from .writeback import WritebackError
from .writers import apply_summary_replacements


def fixed_field_size(entry, payload):
    """Payload excludes the terminator; count it only when this owner has one."""
    needed = len(payload) + (1 if entry.terminator == 'nul' else 0)
    if needed > entry.allocated_length:
        raise WritebackError(f'{entry.entry_id}: needs {needed} bytes, '
                             f'fixed capacity {entry.allocated_length}')
    return needed


def load_production_summary_capacity(root):
    root = Path(root)
    table = load_text_table(root/'vendor/upstream-python/project/tbl_all.json')
    manifest = json.loads((root/'manifests/zh-release-font-validation.json').read_text())
    proposal = json.loads((root/manifest['proposal']['path']).read_text())
    overrides = {a['character']:int(a['code'], 16) for a in proposal['assignments']}
    overrides.update({a['character']:int(a['code'], 16)
                      for a in proposal.get('surface_alias_assignments', [])})
    overrides.update(original_fullwidth_ascii_overrides(table))
    return load_native_summary_capacity(root, table, overrides)


def load_native_summary_capacity(root, table, overrides):
    root = Path(root)
    cfg = json.loads((root/'config/editions/original/edition.json').read_text())
    iso = root/cfg['source_iso']['path']
    members = member_map(scan_iso9660(iso))
    def read(name):
        e = members[name]
        with iso.open('rb') as stream:
            stream.seek(e.extent_lba*2048)
            return stream.read(e.size)
    exe = read(cfg['executable']['member'])
    if hashlib.sha256(exe).hexdigest() != cfg['executable']['sha256']:
        raise WritebackError('native summary executable identity mismatch')
    archive = read('DATA/MTV_PROS.BIN')
    offsets = read_executable_archive_offsets(exe, CORE_ARCHIVE_SPECS['MTV_PROS.BIN'], len(archive))
    chunks = {}; entries = {}
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        data = decode_production(archive[start:end]).output
        chunks[index] = data
        entries.update({e.entry_id:e for e in parse_summary(data, table, chunk_index=index).entries})
    return dict(chunks=chunks, entries=entries, table=table, overrides=overrides,
                archive_sha256=hashlib.sha256(archive).hexdigest())


def preflight_summary_fields(replacements, context):
    """Run the production fixed-allocation writer on each proposed field group.

    No capacity is borrowed from a neighbouring field. No section lengths,
    text offsets, allocations or following records are relocated to make it fit.
    """
    groups = {}; sizes = []
    for identity, text in replacements.items():
        entry = context['entries'][identity]
        text = normalize_original_fullwidth_ascii(text).replace(' ', '　')
        payload = encode_text(text, context['table'], overrides=context['overrides'])
        needed = fixed_field_size(entry, payload)
        sizes.append(dict(id=identity, encodedBytes=needed, capacityBytes=entry.allocated_length))
        groups.setdefault(int(identity.split('/')[1]), {})[identity] = text
    for chunk, fields in groups.items():
        output = apply_summary_replacements(context['chunks'][chunk], context['table'],
                                            chunk_index=chunk, replacements=fields,
                                            overrides=context['overrides'])
        if len(output)!=len(context['chunks'][chunk]):
            raise WritebackError('fixed summary write changed decoded chunk size')
    return sizes


def layout_summary_group(replacements, context):
    """Optimize one verified same-screen group through the browser/Node core."""
    from .js_layout import layout_batch, JsLayoutError
    fields = []
    for identity, text in replacements.items():
        entry = context['entries'][identity]
        fields.append(dict(id=identity, text=text, capacityBytes=entry.allocated_length,
                           terminatorBytes=1 if entry.terminator=='nul' else 0))
    chars = set(''.join(replacements.values()))
    byte_map = {ch:len(encode_text(normalize_original_fullwidth_ascii(ch).replace(' ','　'),
                    context['table'], overrides=context['overrides']))for ch in chars}
    response = layout_batch([dict(action='layout_fields', scene='main_scroll', fields=fields,
        options=dict(resourceId=next(iter(replacements)), maxLines=len(fields),
                     encodedCharacterBytes=byte_map))])[0]
    if not response['ok']:
        raise JsLayoutError(response['error'])
    result = response['result']
    proposed = {f['id']:f['text']for f in result['fields']}
    if ''.join(proposed.values()) != ''.join(replacements.values()):
        raise WritebackError('fixed-field solver changed authored text')
    preflight_summary_fields(proposed, context)
    return result
