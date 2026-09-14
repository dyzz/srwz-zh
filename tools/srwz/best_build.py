"""BEST edition backend for freshly compiled shared Chinese inputs.

The Original compiler is a shared text/layout frontend for this backend. Every
run binds that intermediate to the same input snapshot. Native BEST bytes,
typed text owners and checked edition contracts determine the final output;
no alpha snapshot, fuzzy matching or editorial replacement is used here.
"""
from __future__ import annotations

import bisect
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import struct

from .codec import decode_production as decode, encode
from .compdata_best_corrections import CORRECTIONS
from .edition import EditionError, json_bytes, load_json, project_path
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file, sha256_file
from .text import TextTable, decode_text, load_text_table, original_fullwidth_ascii_overrides, project_runtime_text_table
from .ui_name_tables import verify_name_table
from .library_protagonist_names import (
    EDITIONS as LIBRARY_NAME_EDITIONS, FUNCTION_SIZE as LIBRARY_NAME_SIZE,
    apply_library_protagonist_names,
)
from .battle_square_skip import apply_battle_square_skip, executable_write_ranges as square_skip_ranges


def require(condition, message):
    if not condition:
        raise EditionError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def words(data):
    require(len(data) % 4 == 0, 'unaligned offset table')
    return list(struct.unpack('<' + 'I' * (len(data) // 4), data))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def project_shared_edits(original, native, compiled, *, shift=0, pointer_delta=0x800,
                         text_mask=None, label=''):
    """Project a compiled field only with an exact or typed native preimage.

    The two equal input cases preserve official native changes, including the
    four COMPDATA corrections already present in both native and shared input.
    A text ownership mask never authorizes a differing neighbouring byte.
    """
    require(len(original) == len(compiled), f'{label}: shared decoded size drift')
    out = bytearray(native)
    for offset in range(0, len(original) - 3, 4):
        target = offset + (shift(offset) if callable(shift) else shift)
        x, z = u32(original, offset), u32(compiled, offset)
        if x == z:
            continue
        require(target + 4 <= len(native), f'{label}: mapped field outside native allocation')
        y = u32(native, target)
        if y == z:
            continue
        if x != y:
            if 0x100000 <= x < 0x2000000 and y - x == pointer_delta and 0x100000 <= z < 0x2000000:
                z += pointer_delta
            elif text_mask is not None and all(original[offset+j] == native[target+j] or text_mask[offset+j] for j in range(4)):
                pass
            else:
                raise EditionError(f'{label}: unknown native field overlap at 0x{offset:X}: {x:08x}/{y:08x}/{z:08x}')
        struct.pack_into('<I', out, target, z)
    # Decoded production blocks are aligned; never silently drop a tail edit.
    require(original[len(original)//4*4:] == compiled[len(original)//4*4:], f'{label}: unaligned shared tail edit')
    return out


class BestCompiler:
    def __init__(self, root: Path, common: Path, input_digest: str):
        self.root, self.common, self.input_digest = root.resolve(), common.resolve(), input_digest
        self.work = self.root / 'work/build/best-current'
        self.work.mkdir(parents=True, exist_ok=True)
        self.contract = load_json(root / 'config/editions/best/source-layout.json')
        require(self.contract['schema_version'] == 1, 'BEST layout schema drift')
        self.config = load_json(common / 'config/iso/zh-release-current-build.json')
        self.square_skip = load_json(common / 'config/full-story-components.json')['battle_square_skip']
        self.names = [r['member'] for r in self.config['replacements']]
        expected_count = 24 + int('KURODATA/KVPDATA.BIN' in self.names)
        require(len(self.names) == len(set(self.names)) == expected_count, 'shared component membership drift')
        self.native = {}
        self.images = {}
        for version, directory, elf in [('original', common, 'SLPS_258.87'), ('best', root, 'SLPS_732.70')]:
            profile = load_json(root / f'config/editions/{version}/edition.json')
            path = project_path(directory, profile['source_iso']['path'], 'rom')
            require(path.stat().st_size == profile['source_iso']['size'] and sha256_file(path) == profile['source_iso']['sha256'], f'{version} source ISO drift')
            image = scan_iso9660(path)
            self.images[version] = (path, image)
            members = member_map(image)
            source = {}
            with path.open('rb') as stream:
                for name in self.names:
                    member = elf if name.startswith('SLPS_') else name
                    row = members[member]
                    stream.seek(row.extent_lba * 2048)
                    source[member] = stream.read(row.size)
            self.native[version] = source
            require(sha(source[elf]) == self.contract['provenance'][f'{version}_elf_sha256'], f'{version} layout source drift')
        self.compiled = {}
        for row in self.config['replacements']:
            path = project_path(common, row['source'], 'work')
            data = path.read_bytes()
            require(len(data) == row['size'] and sha(data) == row['sha256'], f'shared component drift: {row["member"]}')
            self.compiled[row['member']] = data
        self.table = load_text_table(root / 'vendor/upstream-python/project/tbl_all.json')
        assignments = load_json(common / 'config/encoding/zh-release-font-assignments.json')
        chars = dict(self.table.characters)
        for key in ['primary_assignments', 'surface_alias_assignments', 'source_compatibility_assignments']:
            chars.update({int(r['code'], 16): r['character'] for r in assignments[key]})
        self.zh_table = TextTable(chars, self.table.tags)
        self.spans = self.contract['elf_spans']
        self.span_starts = [r[0] for r in self.spans]
        require(all(a[1] <= b[0] for a, b in zip(self.spans, self.spans[1:])), 'overlapping ELF layout spans')
        self.archive_tables = {r['member']: r for r in self.contract['archive_tables']}
        self.outputs, self.tables, self.archive_proofs = {}, {}, {}
        self.stage_proofs = []

    def mapped_elf_offset(self, offset):
        index = bisect.bisect_right(self.span_starts, offset) - 1
        require(index >= 0 and offset + 4 <= self.spans[index][1], f'undeclared ELF write at 0x{offset:X}')
        start, _, target = self.spans[index]
        return target + offset - start

    def offsets(self, member, version):
        data = self.compiled if version == 'compiled' else self.native[version]
        if member == 'DATA/STAGE.BIN':
            result = words(data['HEDBDY/HB.BIN'][30320:31144])
        elif member == 'DATA/COMPDATA.BN':
            return [0, len(data[member])]
        else:
            spec = self.archive_tables[member]
            start = spec['best_start' if version == 'best' else 'original_start']
            elf = data['SLPS_732.70' if version == 'best' else 'SLPS_258.87']
            result = words(elf[start:start + 4*spec['count']])
        require(result[0] == 0 and all(a <= b for a, b in zip(result, result[1:])) and result[-1] <= len(data[member]), f'{member}: {version} offset table drift')
        if result[-1] != len(data[member]):
            result.append(len(data[member]))
        return result

    def parse_stage(self, data, version, index):
        from .stage import parse_stage
        elf = self.native['best']['SLPS_732.70'] if version == 'best' else self.native['original']['SLPS_258.87']
        base, table = (0x756EF0, 0x2FF830) if version == 'best' else (0x7566F0, 0x2FF0B0)
        return parse_stage(data, self.zh_table if version == 'compiled' else self.table,
                           stage_index=index, function_address=u32(elf, table+index*4), base_address=base)

    def text_payload(self, data, offset):
        return data[offset:decode_text(data, offset, self.zh_table).end]

    def compile_stage(self, index, original, native, compiled):
        parsed = {v: self.parse_stage(d, v, index) for v, d in [('original', original), ('best', native), ('compiled', compiled)]}
        entries = {v: {e.entry_id: e for e in p.entries if e.pointer_offset is not None and e.text_offset is not None} for v, p in parsed.items()}
        require(set(entries['original']) == set(entries['best']) == set(entries['compiled']), f'STAGE {index}: text owner identity mismatch')
        revisions = {r['id']: r for r in self.contract['stage_source_revisions']}
        for key, entry in entries['original'].items():
            other = entries['best'][key]
            if entry.text != other.text:
                revision = revisions.get(key)
                require(revision is not None and (entry.text, other.text) == (revision['original'], revision['best']), f'{key}: undeclared native source revision')
        layout = self.contract['stage_layouts'].get(str(index), {})
        shift = layout.get('shift', 0)
        mask = bytearray(len(original))
        regions = []
        for entry in entries['original'].values():
            end = decode_text(original, entry.text_offset, self.table).end
            limit = min(len(original), (end+15)//16*16)
            while end < limit and original[end] == 0:
                end += 1
            regions.append((entry.text_offset, end))
            mask[entry.text_offset:end] = b'\1' * (end-entry.text_offset)
        if index == 0:
            require(original[:0x4400] == compiled[:0x4400], 'STAGE 0: shared edit before system dialogue allocation')
            mask[0x4400:] = b'\1' * (len(original)-0x4400)
        merge_source = native
        if layout.get('shared_text_tail'):
            # Two shortened Japanese pools can use the common compiler's
            # existing allocation, within the unchanged native decoded size.
            tail = min(lo for lo, hi in regions)
            require(len(original) == len(native) == len(compiled), f'STAGE {index}: native tail capacity')
            regions = [(tail, len(original))]
            mask[tail:] = b'\1' * (len(original)-tail)
            adjusted = bytearray(native)
            adjusted[tail:] = original[tail:]
            for offset in range(0, tail-3, 4):
                x, y, z = u32(original, offset), u32(native, offset), u32(compiled, offset)
                if 0x7566F0+tail <= x < 0x7566F0+len(original):
                    require(y-x in [0x800, 0x7F0, 0x7E0, 0x6B0] and 0x7566F0+tail <= z < 0x7566F0+len(original), f'STAGE {index}: native tail owner drift')
                    struct.pack_into('<I', adjusted, offset, x+0x800)
            for key, entry in entries['original'].items():
                require(entries['best'][key].pointer_offset == entry.pointer_offset, f'{key}: native owner site drift')
                struct.pack_into('<I', adjusted, entry.pointer_offset, 0x756EF0+entry.text_offset)
            merge_source = bytes(adjusted)
        offset_shift = (lambda o: shift if o < layout['second_region'] else layout['second_shift']) if 'second_region' in layout else shift
        out = project_shared_edits(original, merge_source, compiled, shift=offset_shift, pointer_delta=0x800+shift, text_mask=mask, label=f'STAGE {index}')
        for lo, hi in regions:
            out[lo+shift:hi+shift] = compiled[lo:hi]
        if layout.get('shared_text_tail'):
            for offset in range(0, tail-3, 4):
                if 0x7566F0+tail <= u32(original, offset) < 0x7566F0+len(original):
                    struct.pack_into('<I', out, offset, u32(compiled, offset)+0x800)
        targets = {}
        for key, entry in entries['original'].items():
            best_entry, common_entry = entries['best'][key], entries['compiled'][key]
            require(best_entry.pointer_offset == entry.pointer_offset+shift, f'{key}: BEST pointer site drift')
            dest = common_entry.text_offset+shift
            payload = self.text_payload(compiled, common_entry.text_offset)
            require(out[dest:dest+len(payload)] == payload, f'{key}: compiled payload placement mismatch')
            struct.pack_into('<I', out, best_entry.pointer_offset, 0x756EF0+dest)
            targets[entry.text_offset] = (best_entry.text_offset, common_entry.text_offset)
        if layout.get('shared_text_tail'):
            selected = {e.pointer_offset for e in entries['original'].values()}
            for offset in range(0, len(original)-3, 4):
                if any(mask[offset:offset+4]) or offset in selected:
                    continue
                target = u32(original, offset)-0x7566F0
                if target in targets:
                    bt, ct = targets[target]
                    require(u32(native, offset) == 0x756EF0+bt and u32(compiled, offset) == 0x7566F0+ct, f'STAGE {index}: alias preimage drift')
                    struct.pack_into('<I', out, offset, 0x756EF0+ct)
        require(len(out) == len(native), f'STAGE {index}: decoded size changed')
        self.verify_stage_texts(index, bytes(out), compiled)
        self.stage_proofs.append({'index': index, 'entries': len(entries['best']), 'native_sha256': sha(native), 'decoded_sha256': sha(out), 'compiled_sha256': sha(compiled)})
        return bytes(out)

    def verify_stage_texts(self, index, output, compiled):
        from .stage import parse_stage
        functions = self.native['best']['SLPS_732.70']
        actual = parse_stage(output, self.zh_table, stage_index=index,
                             function_address=u32(functions, 0x2FF830+4*index), base_address=0x756EF0)
        common = self.parse_stage(compiled, 'compiled', index)
        a, b = ({e.entry_id: e for e in p.entries} for p in (actual, common))
        require(set(a) == set(b), f'STAGE {index}: final owner identity drift')
        for key, expected in b.items():
            require(a[key].text == expected.text and a[key].speaker_id == expected.speaker_id, f'{key}: shared Chinese semantic mismatch')
            if expected.pointer_offset is not None and expected.text_offset is not None:
                require(self.text_payload(output, a[key].text_offset) == self.text_payload(compiled, expected.text_offset), f'{key}: shared encoded control/payload mismatch')

    def compile_elf(self):
        a, b, c = self.native['original']['SLPS_258.87'], self.native['best']['SLPS_732.70'], self.compiled['SLPS_258.87']
        out, writes, used = bytearray(b), [], set()
        instructions = {r['original_offset']: r for r in self.contract['elf_instructions']}
        slot = self.contract['elf_support_attack_slot']
        library_start = LIBRARY_NAME_EDITIONS['original']['offset']
        library_end = library_start + LIBRARY_NAME_SIZE
        library_changed = a[library_start:library_end] != c[library_start:library_end]
        if library_changed:
            _, shared_library_names = apply_library_protagonist_names(c)
            require(shared_library_names['already_patched'], 'shared LIBRARY name formatter missing')
        archive_offsets = {o for spec in self.archive_tables.values()
                           for r in (spec, *spec.get('aliases', []))
                           for o in range(r['original_start'], r['original_start']+4*r['count'], 4)}
        # The square-skip hook is edition-specific code: it is re-applied from
        # the BEST contract below instead of being projected word by word.
        square_skip = getattr(self, 'square_skip', None)  # absent only in unit-test fixtures
        square_skip_offsets = {o for lo, hi in square_skip_ranges(square_skip, 'original') for o in range(lo, hi, 4)} if square_skip else set()
        for offset in range(0, len(c)-3, 4):
            if a[offset:offset+4] == c[offset:offset+4] or slot['original_start'] <= offset < slot['original_end'] or offset in archive_offsets or offset in square_skip_offsets:
                continue
            if library_start <= offset < library_end:
                continue  # Compile from the independently pinned native function below.
            target = self.mapped_elf_offset(offset)
            require(target not in used, 'duplicate ELF destination')
            used.add(target)
            x, y, z = u32(a, offset), u32(b, target), u32(c, offset)
            if offset < 0x2F0000:
                guard = instructions.get(offset)
                require(guard is not None and guard['best_offset'] == target and a[offset:offset+4].hex() == guard['original'] and b[target:target+4].hex() == guard['best'], 'undeclared ELF instruction preimage')
            if x != y:
                if (x, y, z) == (0x80238572, 0x80238D72, 0x8023856E):
                    z = 0x80238D6E
                else:
                    require(offset in (0x33CF0C, 0x344724, 0x344728), f'ELF conflicting field at 0x{offset:X}')
            struct.pack_into('<I', out, target, z)
            writes.append([target, target+4])
        # Bind the shorter native slot to this batch's corpus and retain the
        # frontend's reviewed glyph aliases, including punctuation aliases.
        corpus = load_json(self.root / 'corpus/zh/menu/system-ui-skills.json')
        translation = next(e['translation'] for e in corpus['entries'] if e['id'] == slot['translation_id'])
        payload = self.text_payload(c, slot['original_start'])
        require(decode_text(payload, 0, self.zh_table).text == translation, 'support attack source/common binding mismatch')
        lo, hi = slot['best_start'], slot['best_end']
        require(len(payload) <= hi-lo, 'BEST support attack description exceeds native slot')
        out[lo:hi] = payload + bytes(hi-lo-len(payload))
        writes.append([lo, hi])
        if library_changed:
            patched, self.library_name_proof = apply_library_protagonist_names(bytes(out), 'best')
            out = bytearray(patched)
            start = LIBRARY_NAME_EDITIONS['best']['offset']
            writes.append([start, start + LIBRARY_NAME_SIZE])
        if square_skip:
            patched, self.square_skip_proof = apply_battle_square_skip(bytes(out), square_skip, 'best')
            require(not self.square_skip_proof['already_applied'] and self.square_skip_proof['all_replacements_exact'], 'BEST square-skip preimage drift')
            out = bytearray(patched)
            writes.extend([lo, hi] for lo, hi in square_skip_ranges(square_skip, 'best'))
        self.elf_writes = writes
        return out

    def verify_elf_policy(self, output):
        native = self.native['best']['SLPS_732.70']
        _, names = apply_library_protagonist_names(bytes(output), 'best')
        require(names['already_patched'], 'BEST LIBRARY name formatter missing')
        guards = [(0x153E94,0x00A21024,0x00A21025), (0x15408C,0x00821024,0x00821025),
                  (0x154134,0x00A21024,0x00A21025), (0x154454,0x00451024,0x00451025),
                  (0x1A3DE0,0x0C04E64C,0x0C04E64C), (0x1A3F14,0x10430008,0x10000008),
                  (0x2016F4,0x80238D72,0x80238D6E), (0x3EB260,0x80238D72,0x80238D6E)]
        for address, before, after in guards:
            offset = address-0xFE580
            require(u32(native, offset) == before and u32(output, offset) == after, f'BEST policy guard at 0x{address:X}')
        restored = bytearray(output)
        for lo, hi in self.elf_writes:
            restored[lo:hi] = native[lo:hi]
        require(bytes(restored) == native, 'ELF change outside declared text/code/table writes')

    def compile_compdata(self, a, b, c):
        mask = bytearray(len(a))
        slots = [(0x244CE,0x244DC), (0x2457E,0x2458C), (0x6C4C0,0x6C550), (0x6C550,0x6C5E0)]
        for lo, hi in slots:
            mask[lo:hi] = b'\1'*(hi-lo)
        out = project_shared_edits(a, b, c, text_mask=mask, label='COMPDATA')
        for lo, hi in slots:
            payload = self.text_payload(c, lo)
            require(len(payload) <= hi-lo, 'COMPDATA fixed field overflow')
            out[lo:hi] = payload+bytes(hi-lo-len(payload))
        require(out[0x80:0x8C0] == b[0x80:0x8C0] and u32(out, 8) == 0x6D7000, 'BEST COMPDATA native code/base drift')
        for field in CORRECTIONS:
            lo, hi = field.offset, field.offset+field.width
            expected = field.best.to_bytes(field.width, 'little')
            require(b[lo:hi] == out[lo:hi] == c[lo:hi] == expected, f'BEST native correction drift: {field.field_id}')
        return bytes(out)

    def compile_zkan(self, a, b, c):
        from .library import parse_zkn_decoded_chunk, parse_runtime_zkn_decoded_chunk, zkan_escape_transform
        aa, bb = [parse_zkn_decoded_chunk(data) for data in (a,b)]
        cc = parse_runtime_zkn_decoded_chunk(c, self.zh_table)
        require([f.tag for f in aa.fields] == [f.tag for f in bb.fields] == [f.tag for f in cc.fields], 'ZKAN field identity drift')
        records = bytearray()
        for original, native, compiled in zip(aa.fields, bb.fields, cc.fields):
            raw = compiled.data
            if original.data != native.data:
                require(native.tag in ('VOIC','ACTR'), f'unknown ZKAN native field change: {native.tag}')
            if native.tag == 'VOIC':
                raw = native.data
            records.extend(native.tag.encode()+struct.pack('<I',len(raw))+raw)
        payload = b'ZKAN'+cc.kind.encode()+struct.pack('<II',cc.version,12)+b'DSIZ'+struct.pack('<I',len(records)+8)+b'DATA'+struct.pack('<I',len(records))+records
        payload += bytes((-len(payload))%16)
        output = struct.pack('<8I',1,32,0,len(payload),len(payload),0,0,0)+zkan_escape_transform(payload)
        parsed = parse_runtime_zkn_decoded_chunk(output, self.zh_table)
        for native, compiled, actual in zip(bb.fields, cc.fields, parsed.fields):
            require(actual.data == (native.data if actual.tag == 'VOIC' else compiled.data), 'ZKAN shared text/native voice readback mismatch')
        return output

    def compile_srvc(self):
        from .srvc import parse_srvc_archive, parse_srvc_archive_with_layout
        a, b, c = self.native['original']['BTL/SRVC.BIN'], self.native['best']['BTL/SRVC.BIN'], self.compiled['BTL/SRVC.BIN']
        ao, bo, co = [tuple(words(d['BTL/SRVC.SEG'])) for d in (self.native['original'],self.native['best'],self.compiled)]
        pa, pb = parse_srvc_archive(a, ao, self.table), parse_srvc_archive(b, bo, self.table)
        pc = parse_srvc_archive_with_layout(c, co, pa, self.zh_table)
        by_text = {}
        for original, compiled in zip(pa,pc):
            require(len(original.records) == len(compiled.records), 'shared subtitle record count drift')
            for x, z in zip(original.records,compiled.records):
                payload = c[z.archive_text_start:z.archive_text_end]
                require(by_text.setdefault(x.text,payload) == payload, 'ambiguous shared subtitle source binding')
        for row in self.contract['battle_source_aliases']:
            require(row['original'] in by_text, 'missing subtitle source revision binding')
            payload = by_text[row['original']]
            require(row['best'] not in by_text or by_text[row['best']] == payload, 'conflicting revised subtitle binding')
            by_text[row['best']] = payload
        output, headroom, count = bytearray(b), [], 0
        for chunk in pb:
            if not chunk.records:
                continue
            parts, cursor = [], 0
            for record in chunk.records:
                require(record.text in by_text, f'unbound BEST subtitle: {record.text}')
                payload = by_text[record.text]
                struct.pack_into('<I',output,chunk.archive_start+chunk.text_index_start+record.record_index*8+4,cursor)
                parts.append(payload); cursor += len(payload); count += 1
            capacity = chunk.indexed_text_end-chunk.text_pool_start
            require(cursor <= capacity, f'SRVC {chunk.chunk_index}: native text allocation overflow')
            lo, hi = chunk.archive_start+chunk.text_pool_start, chunk.archive_start+chunk.indexed_text_end
            output[lo:hi] = b''.join(parts)+bytes(capacity-cursor)
            require(output[hi:chunk.archive_end] == b[hi:chunk.archive_end], 'SRVC native tail drift')
            headroom.append(capacity-cursor)
        check = parse_srvc_archive_with_layout(bytes(output), bo, pb, self.zh_table)
        for source, actual in zip(pb, check):
            require(len(source.records) == len(actual.records), 'BEST subtitle final count drift')
            for s,t in zip(source.records,actual.records):
                require(s.metadata == t.metadata and output[t.archive_text_start:t.archive_text_end] == by_text[s.text], 'BEST subtitle metadata/text readback mismatch')
        require(count == 58751, 'BEST subtitle coverage drift')
        self.srvc_proof = {'records':count, 'additional_native_records':count-sum(len(c.records) for c in pa), 'minimum_headroom':min(headroom), 'native_metadata_and_tail_preserved':True}
        return bytes(output)

    def pack_archive(self, member, prepared):
        def compress(row):
            index, streams, decoded, target = row
            key = sha(target+streams['best'][:16])
            cached = self.work / 'compressed-cache' / key
            if cached.is_file():
                payload = cached.read_bytes()
                require(decode(payload).output == target, 'BEST compressed cache drift')
            else:
                payload = None
                for version in ('best','compiled','original'):
                    if target == decoded[version]:
                        result = decode(streams[version]); payload = streams[version][:result.consumed]; break
                if payload is None:
                    source = decode(streams['best'])
                    payload = encode(target,strategy='rust-fit',flags=source.flags,header_unknown_0=source.metadata.get('header_unknown_0'),header_unknown_1=source.metadata.get('header_unknown_1',0))
                require(decode(payload).output == target, f'{member}/{index}: compression roundtrip')
                cached.parent.mkdir(parents=True,exist_ok=True); cached.write_bytes(payload)
            return index, payload, target
        with ThreadPoolExecutor(max_workers=4) as pool:
            items = list(pool.map(compress,prepared))
        table, parts, proofs = [0], [], []
        for index, payload, target in items:
            require(index == len(parts), 'native archive chunk sequence drift')
            part = payload+bytes((-len(payload))%16)
            parts.append(part); table.append(table[-1]+len(part))
            proofs.append({'index':index,'decoded_sha256':sha(target),'decoded_size':len(target)})
        capacity = len(self.native['best'][member])
        require(table[-1] <= capacity, f'{member}: BEST member capacity exceeded {table[-1]}/{capacity}')
        output = b''.join(parts)+bytes(capacity-table[-1]); table[-1] = capacity
        for (_, _, target), lo, hi in zip(items,table,table[1:]):
            require(decode(output[lo:hi]).output == target, f'{member}: packed archive readback')
        self.outputs[member], self.tables[member], self.archive_proofs[member] = output, table, proofs
        print(f'[best] {member}: {len(items)} decoded chunks', flush=True)

    def write_archive_tables(self, elf):
        """Update every declared runtime consumer of each packed archive.

        HSFC has separate summary and Scenario Chart loader tables. The latter
        includes an end sentinel and must move with the same compressed streams.
        Validate each native alias against the primary table before writing it.
        """
        proofs = []
        for member, spec in self.archive_tables.items():
            if member not in self.outputs:
                continue
            table = self.tables.get(member)
            if table is None:
                table = self.offsets(member, 'compiled')
                table[-1] = len(self.outputs[member])
            native_tables = {v: self.offsets(member, v) for v in ('original', 'best')}
            for site in (spec, *spec.get('aliases', [])):
                start, count = site['best_start'], site['count']
                require(len(table) in (count, count+1), f'{member}: table slot count drift')
                for version, name in [('original', 'SLPS_258.87'), ('best', 'SLPS_732.70')]:
                    source_start = site[f'{version}_start']
                    actual = words(self.native[version][name][source_start:source_start+4*count])
                    require(actual == native_tables[version][:count],
                            f'{member}: {version} archive table alias preimage drift at 0x{source_start:X}')
                payload = struct.pack('<'+'I'*count, *table[:count])
                elf[start:start+len(payload)] = payload
                self.elf_writes.append([start, start+len(payload)])
                require(words(elf[start:start+len(payload)]) == table[:count],
                        f'{member}: runtime archive table readback')
                proofs.append({'member': member, 'best_start': start, 'count': count,
                               'offsets': table[:count]})
        return proofs

    def compile(self):
        elf = self.compile_elf()
        changed = {'SLPS_258.87','DATA/COMPDATA.BN','DATA/STAGE.BIN','DATA/NISVDATA.BIN','DATA/HSFC.BIN','DATA/MTVZKNPT.BIN','EFF/VEFF2DX.BIN','HEDBDY/HB.BIN','BTL/SRVC.BIN','BTL/SRVC.SEG'}
        for member in self.names:
            if member in changed:
                continue
            require(self.native['original'][member] == self.native['best'][member], f'{member}: cannot reuse a different native source')
            data, capacity = self.compiled[member], len(self.native['best'][member])
            require(len(data) <= capacity, f'{member}: shared resource size overflow')
            self.outputs[member] = data+bytes(capacity-len(data))
        for member in ['DATA/COMPDATA.BN','DATA/STAGE.BIN','DATA/NISVDATA.BIN','DATA/HSFC.BIN','DATA/MTVZKNPT.BIN','EFF/VEFF2DX.BIN']:
            offsets = {v:self.offsets(member,v) for v in ('original','best','compiled')}
            require(len({len(o) for o in offsets.values()}) == 1, f'{member}: native chunk count mismatch')
            prepared = []
            for index in range(len(offsets['best'])-1):
                streams = {v:(self.compiled if v=='compiled' else self.native[v])[member][os[index]:os[index+1]] for v,os in offsets.items()}
                decoded = {v:decode(s).output for v,s in streams.items()}
                a,b,c = (decoded[v] for v in ('original','best','compiled'))
                if member == 'DATA/STAGE.BIN':
                    target = self.compile_stage(index,a,b,c)
                elif member == 'DATA/COMPDATA.BN':
                    target = self.compile_compdata(a,b,c)
                elif member == 'DATA/NISVDATA.BIN' and index == 6:
                    require(a[:0xEB70] == b[:0xEB70] and a[0xEB70+2064:] == b[0xEB70+2064:], 'NISV revision escaped Q&A page')
                    target = c  # Both corrected descriptions come from this batch's corpus.
                elif a == b:
                    target = c
                elif a == c:
                    target = b
                elif member == 'DATA/MTVZKNPT.BIN':
                    target = self.compile_zkan(a,b,c)
                elif member == 'EFF/VEFF2DX.BIN':
                    target = bytes(project_shared_edits(a,b,c,label=f'{member}/{index}'))
                else:
                    raise EditionError(f'unhandled BEST native field revision: {member}/{index}')
                prepared.append((index,streams,decoded,target))
            self.pack_archive(member,prepared)
        self.outputs['BTL/SRVC.BIN'] = self.compile_srvc()
        self.outputs['BTL/SRVC.SEG'] = self.native['best']['BTL/SRVC.SEG']
        hb = bytearray(self.native['best']['HEDBDY/HB.BIN'])
        hb[30320:31144] = struct.pack('<206I',*self.tables['DATA/STAGE.BIN'])
        self.outputs['HEDBDY/HB.BIN'] = bytes(hb)
        archive_table_proofs = self.write_archive_tables(elf)
        self.outputs['SLPS_732.70'] = bytes(elf)
        self.verify_elf_policy(elf)
        name_corpus = load_json(self.common / 'corpus/zh/menu/ui-name-tables.json')
        name_table = project_runtime_text_table(self.zh_table, original_fullwidth_ascii_overrides(self.table))
        original_offsets = self.offsets('DATA/NISVDATA.BIN', 'original')
        lo, hi = original_offsets[4:6]
        original_names = decode(self.native['original']['DATA/NISVDATA.BIN'][lo:hi]).output
        lo, hi = self.tables['DATA/NISVDATA.BIN'][4:6]
        current_names = decode(self.outputs['DATA/NISVDATA.BIN'][lo:hi]).output
        name_proof = {
            'squad_names': verify_name_table(original_names, current_names, name_corpus['squad_names'],
                                            kind='squad', source_table=self.table, runtime_table=name_table),
            'map_names': verify_name_table(self.native['best']['MAP/MAPNAME.BIN'], self.outputs['MAP/MAPNAME.BIN'],
                                          name_corpus['map_names'], kind='map', source_table=self.table,
                                          runtime_table=name_table),
        }

        rows = []
        for member,data in self.outputs.items():
            require(len(data) == len(self.native['best'][member]), f'{member}: fixed native size drift')
            target = self.work / 'components' / member
            target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
            rows.append({'member':member,'path':target.relative_to(self.root).as_posix(),'size':len(data),'sha256':sha(data)})
        report = {'schema_version':1,'edition':'best','input_digest':self.input_digest,'status':'best_components_semantic_readback_passed',
                  'components':rows,'stages':self.stage_proofs,'archives':self.archive_proofs,'srvc':self.srvc_proof,
                  'runtime_archive_tables':archive_table_proofs,'ui_name_tables':name_proof,
                  'library_protagonist_names':self.library_name_proof,'battle_square_skip':self.square_skip_proof,
                  'native_elf_outside_declared_writes_preserved':True,'elf_write_ranges':self.elf_writes,
                  'compdata_native_corrections_preserved':True,'library_policy':'all_valid_entries_without_save_writeback','runtime':'not_tested'}
        write_json(self.work/'component-validation.json',report)
        return report

    def build_iso(self, report):
        source,image = self.images['best']
        target = self.root / 'build/iso/zh-release-best/current-best.iso'
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary = target.with_suffix('.iso.tmp'); copy_file(source,temporary)
        members = member_map(image)
        with temporary.open('r+b') as stream:
            for member,data in self.outputs.items():
                stream.seek(members[member].extent_lba*2048); stream.write(data)
        # Read the actual disc directory again, then compare every member and
        # every gap. This preserves the native ISO/UDF metadata and all LBAs.
        actual = member_map(scan_iso9660(temporary))
        require([(n,m.extent_lba,m.size) for n,m in actual.items()] == [(n,m.extent_lba,m.size) for n,m in members.items()], 'BEST final directory/layout drift')
        intervals = sorted((r.extent_lba*2048,r.extent_lba*2048+r.size,n) for n,r in members.items() if n in self.outputs)
        with source.open('rb') as original, temporary.open('rb') as output:
            cursor = 0
            for lo,hi,name in intervals:
                require(lo >= cursor, 'overlapping ISO replacement extents')
                remaining = lo-cursor
                while remaining:
                    size = min(8<<20,remaining)
                    require(original.read(size) == output.read(size), 'BEST non-replacement bytes drift')
                    remaining -= size
                require(output.read(hi-lo) == self.outputs[name], f'{name}: ISO component readback mismatch')
                original.seek(hi); cursor = hi
            while True:
                block = original.read(8<<20)
                require(output.read(len(block)) == block, 'BEST native tail drift')
                if not block:
                    break
        require(temporary.stat().st_size == source.stat().st_size, 'BEST final ISO size drift')
        temporary.replace(target)
        proof = {'schema_version':1,'status':'best_final_iso_static_content_readback_passed','input_digest':self.input_digest,
                 'iso':{'path':target.relative_to(self.root).as_posix(),'size':target.stat().st_size,'sha256':sha256_file(target)},
                 'source_iso_sha256':sha256_file(source),'member_count':len(members),'replacement_count':len(self.outputs),
                 'stage_chunk_count':len(self.stage_proofs),'stage_text_owner_count':sum(r['entries'] for r in self.stage_proofs),
                 'subtitle_record_count':self.srvc_proof['records'],'all_non_replacement_iso_bytes_preserved':True,
                 'native_member_sizes_and_lbas_preserved':True,'runtime':'not_tested',
                 'component_readback':{'path':(self.work/'component-validation.json').relative_to(self.root).as_posix(),'sha256':sha256_file(self.work/'component-validation.json')}}
        write_json(self.work/'iso-readback.json',proof)
        return proof
