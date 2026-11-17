#!/usr/bin/env python3
"""Assemble one Original disc holding Simplified and Traditional from two single-language builds.

Inputs are two complete ISOs built by the same pipeline: --sc (Simplified, the production build) and --tc
(the same build fed the Traditional corpus, codebook and font). The output is the SC image plus:
  * the boot/title language hook (tools/zh_hant/lang_hook.S) and three static executable words, identical in
    both languages: hook jal at 0x141010, title jal at 0x155cf8, font buffer size 0x3f7d68 = GLYPHS * 288;
  * in DMY (all zero on the source disc): every member whose TC bytes differ, the TC font chunk, and a patch
    file = VMAP rows for those members + the byte diff of the two executables, which the hook applies when the
    memory-card setting (or SELECT) asks for Traditional.

Member handling (anything else fails, so an unsupported difference can never ship silently):
  * SLPS_258.87: diff. The TC executable's VT1 offset table is replaced by the SC one first (the disc keeps
    the SC VT1); the TC font is reached by rewriting the font loader's offset/length loads (0x13a174..a8) and
    the linear glyph fallback (0x13a95c/60) is enabled.
  * DATA/VT1.BIN: only chunk 2 (font: the Traditional build's own font, placed as built) may differ; chunk 8 (stage titles) is handled by a whole-group copy plus
    a constant shift of the TC executable's inner table at 0x41a2b0; any other differing chunk fails (M4).
  * Every other differing member must have a VMAP row: it is copied whole to DMY and its row is repointed.
Checks (§9.5): patch replay reproduces the TC executable (minus the VT1 table); no record touches the hook,
its sites, the music hooks or the heap words; every DMY item reads back; outside the written spans the output
equals the SC image; the SC executable equals the SC build plus the three static words and the hook.
Usage: assemble_dual.py --sc SC.iso --tc TC.iso --out build/iso/test/NAME.iso [--receipt PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srwz.iso9660 import scan_iso9660, member_map  # noqa: E402
from srwz.iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets  # noqa: E402

EXE = 'SLPS_258.87'
CAVE, CAVE_END = 0x78B640, 0x78C4C0      # free tail of the Latin-bank segment (payload ends 0x78b610)
SCRATCH, SCRATCH_MAX = 0x1C00000, 0x80000
GLYPHS = 4992                            # font buffer sized once for both languages (Traditional profile: 4,992)
VT1_TABLE = 0x3F8680                     # executable VT1 offset table (file 0x2fa100), 15 words
FONT_CHUNK, TITLE_GROUP, MENU_CHUNK = 2, 8, 6
TITLE_TABLE, TITLE_COUNT = 0x41A2B0, 117
# Settings-panel text, per display language (each encoded with that language's codebook). MSG_KEYS is the
# order lang_hook.S indexes (pick_msg); the panel line is cursor/blank + label + value, the values come in pairs
# (setting 0 / 1). The selected row starts with ⇒ (stock 0x81CB). The box centres every line by its code count
# (0x139B00: font 6 counts 16 for every code, blanks included), so all three rows are 10 codes (labels 5 codes, padded
# on the left if shorter; values padded to 4 on the right) and line up as a column with the colons aligned. The hint row's
# second blank and its last middle blank are where lang_hook.S draws the ○ / × button sprites; the extra leading blank
# moves the row half a code right, under the middle of the column (user, 2026-11-17). Identical fragments are stored once.
MSG_KEYS = ['cursor', 'blank', 'lbl_lang', 'lbl_zero', 'lbl_quote', 'v_sc', 'v_tc', 'v_dot', 'v_plain', 'v_cn', 'v_jp',
            'hint', 'ok', 'fail', 'nl', 'spare']
# The zero row shows the two zeros themselves: U+E000 / U+E001 stand for the Latin bank's dotted zero (code
# 0x8440, slot 0) and plain zero (0x844A, slot 10); the message box draws those codes' glyphs directly.
MESSAGES = {
    'sc': {'cursor': '⇒', 'blank': '　', 'lbl_lang': '游戏语言：', 'lbl_zero': '数字样式：', 'lbl_quote': '对话引号：',
           'v_sc': '简体中文', 'v_tc': '繁体中文', 'v_dot': '\ue000　　　', 'v_plain': '\ue001　　　', 'v_cn': '中文“”', 'v_jp': '日文「」',
           'hint': '　　保存　　　取消', 'ok': '设定已保存。\n（语言在重新启动游戏后生效）', 'fail': '无法写入记忆卡。', 'nl': '\n', 'spare': ''},
    'tc': {'cursor': '⇒', 'blank': '　', 'lbl_lang': '遊戲語言：', 'lbl_zero': '數字樣式：', 'lbl_quote': '對話引號：',
           'v_sc': '簡體中文', 'v_tc': '繁體中文', 'v_dot': '\ue000　　　', 'v_plain': '\ue001　　　', 'v_cn': '中文“”', 'v_jp': '日文「」',
           'hint': '　　保存　　　取消', 'ok': '設定已保存。\n（語言在重新啟動遊戲後生效）', 'fail': '無法寫入記憶卡。', 'nl': '\n', 'spare': ''},
}
for _m in MESSAGES.values():                         # equal rows (see above); 3 rows + hint fit panel_buf (84 bytes)
    _rows = [(_m[l], (_m[a], _m[b])) for l, a, b in (('lbl_lang', 'v_sc', 'v_tc'), ('lbl_zero', 'v_dot', 'v_plain'),
                                                       ('lbl_quote', 'v_cn', 'v_jp'))]
    assert {1 + len(l) + len(v) for l, vs in _rows for v in vs} == {10}, 'panel rows must be 10 codes'
    assert 3 * (2 * 10 + 1) + 2 * len(_m['hint']) + 1 <= 84, 'panel text exceeds panel_buf'
STOCK_CODES = {'０': '824F', '　': '8140', '：': '8146', '⇒': '81CB', '\ue000': '8440', '\ue001': '844A'}   # stock full-width codes the release codebooks do not list
OPTIONS_MARKER = b'SRWZOPT1'                              # srwz.proportional_hooks.DISPLAY_OPTIONS_MARKER
MENU_LOADER = {0x154C8C: 0x8422_8668, 0x154C90: 0x0002_1080, 0x154C98: 0x00A2_2821, 0x154CA0: 0x0062_1021,
               0x154CA4: 0x8CA5_0000, 0x154CA8: 0x8C42_0000}     # lh v0,-0x7998(at); sll; addu a1; addu v0; lw a1; lw v0
FONT_LOADER = {0x13A174: 0x84238664, 0x13A184: 0x84228666, 0x13A19C: 0x8C650000, 0x13A1A0: 0x8C420000, 0x13A1A8: 0x00453023,
               0x13A95C: 0x1000000C, 0x13A960: 0xA4200062}
FORBIDDEN = [(CAVE, CAVE_END), (0x141010, 0x141018), (0x155CF8, 0x155CFC), (0x3F7D68, 0x3F7D6C), (0x798000, 0x7A0000),
             *((a, a + 8) for a in (0x189580, 0x189B70, 0x189600, 0x18AC10)),                   # music hooks
             *((a, a + 4) for a in (0x1001D0, 0x1001D8, 0x140644, 0x140650, 0x3F3FB4))]         # heap words
sha = lambda b: hashlib.sha256(b).hexdigest()


class Disc:
    def __init__(self, path: Path):
        self.path = path; self.m = member_map(scan_iso9660(path))

    def read(self, name: str) -> bytes:
        e = self.m[name]
        with open(self.path, 'rb') as f:
            f.seek(e.extent_lba * 2048); return f.read(e.size)

    def vmap(self) -> dict:
        with open(self.path, 'rb') as f:
            f.seek(450 * 2048); raw = f.read(4 * 2048)
        rows = {}
        for i in range(0, len(raw) - 47, 48):
            nm = raw[i:i + 40].split(b'\0')[0].decode('ascii', 'replace')
            if not nm: break
            rows[nm.replace('\\\\', '/').strip('/').split(';')[0].upper()] = (i, *struct.unpack_from('<II', raw, i + 40))
        return rows


class Elf:
    def __init__(self, data: bytes):
        self.b = bytearray(data)
        ph, num = struct.unpack_from('<I', data, 28)[0], struct.unpack_from('<H', data, 44)[0]
        self.loads = [h for h in (struct.unpack_from('<8I', data, ph + 32 * i) for i in range(num)) if h[0] == 1 and h[4]]

    def fo(self, va, n=1):
        for t, o, v, p, fs, ms, fl, al in self.loads:
            if v <= va and va + n <= v + fs: return o + va - v
        raise ValueError(hex(va))

    def get(self, va, n=4): return bytes(self.b[self.fo(va, n):self.fo(va, n) + n])
    def word(self, va): return struct.unpack('<I', self.get(va))[0]
    def put(self, va, data): self.b[self.fo(va, len(data)):self.fo(va, len(data)) + len(data)] = data
    def putw(self, va, w): self.put(va, struct.pack('<I', w))


def codebook_messages(codebooks: dict) -> str:
    out = ['# generated by assemble_dual.py: settings-panel text per display language, each in its own codebook',
           '# (surface-alias punctuation codes, as the native message box uses); msg_table holds offsets from msg_base',
           'msg_base:']
    labels, table = {}, []
    for lang, path in codebooks.items():
        led = json.loads(Path(path).read_text(encoding='utf-8')); code = dict(STOCK_CODES)
        for a in led['surface_alias_assignments']:
            if a['character'] in '。？（），、！': code.setdefault(a['character'], a['code'])
        for k in ('primary_assignments', 'surface_alias_assignments', 'source_compatibility_assignments'):
            for a in led[k]: code.setdefault(a['character'], a['code'])
        for k in MSG_KEYS:
            t = MESSAGES[lang][k]
            # ASCII passes through as native single-byte bytes (in the message box a bare '<' is the name substitution,
            # not an icon: the help-bar button icons are sprites drawn by their own screens)
            missing = [c for c in t if ord(c) >= 0x80 and c not in code]
            if missing: raise SystemExit(f'{lang} codebook lacks message characters {missing}')
            b = b''.join(c.encode('ascii') if ord(c) < 0x80 else bytes.fromhex(code[c]) for c in t) + b'\0'
            if b not in labels:
                labels[b] = f'msg_{lang}_{k}'
                out += [f'{labels[b]}:  # ' + t.replace('\n', ' / '), '        .byte ' + ', '.join(str(x) for x in b)]
            table.append(labels[b])
    out += ['        .align  1', 'msg_table:'] + [f'        .hword  {l} - msg_base' for l in table]
    return '\n'.join(out) + '\n'


def options_address(*exes) -> int:
    """Address of the proportional hooks' display-options word (after its marker), the same in every build."""
    found = set()
    for exe in exes:
        hits = [v + i for t, o, v, p, fs, ms, fl, al in exe.loads
                for i in range(0, fs - 11, 4) if bytes(exe.b[o + i:o + i + 8]) == OPTIONS_MARKER]
        if len(hits) != 1: raise SystemExit('display-options word not found exactly once')
        found.add(hits[0] + len(OPTIONS_MARKER))
    if len(found) != 1: raise SystemExit('display-options word differs between the builds')
    return found.pop()


def assemble_hook(work: Path, patch_lba: int, patch_sectors: int, codebooks: dict, options: int):
    work.mkdir(parents=True, exist_ok=True)
    (work / 'params.inc').write_text(f'        .equ PATCH_LBA, {patch_lba:#x}\n        .equ PATCH_SECTORS, {patch_sectors}\n'
                                     f'        .equ SCRATCH, {SCRATCH:#x}\n        .equ OPTIONS, {options:#x}\n')
    (work / 'messages.inc').write_text(codebook_messages(codebooks))
    title = 'スーパーロボット大戦Ｚ言語設定'.encode('shift_jis'); assert len(title) <= 64
    (work / 'icon_title.inc').write_text('icon_title:  # card browser title (Shift-JIS, line 2 from byte 22)\n        .byte '
                                         + ', '.join(str(x) for x in title + bytes(64 - len(title))) + '\n')
    def tool(t, *a, out=False):
        r = subprocess.run(['mipsel-linux-gnu-' + t, *a], check=True, capture_output=True, text=True); return r.stdout
    tool('as', '-EL', '-mips3', '-mabi=o64', '-I', str(work), '-o', str(work / 'hook.o'), str(Path(__file__).with_name('lang_hook.S')))
    tool('ld', '-EL', f'-Ttext={CAVE:#x}', '-e', 'lang_hook', '-o', str(work / 'hook.elf'), str(work / 'hook.o'))
    tool('objcopy', '-O', 'binary', '-j', '.text', str(work / 'hook.elf'), str(work / 'hook.bin'))
    (work / 'hook.o').unlink()
    dis = re.split(r'<(?:setting|panel_buf)>:', tool('objdump', '-d', str(work / 'hook.elf')))[0]   # code only
    if ' $at' in dis or ',at' in dis or '\tat,' in dis: raise SystemExit('assembler expanded a macro through $at')
    syms = tool('nm', str(work / 'hook.elf')); (work / 'symbols.txt').write_text(syms)
    syms = {l.split()[2]: int(l.split()[0], 16) for l in syms.splitlines() if len(l.split()) == 3}
    code = (work / 'hook.bin').read_bytes()
    if syms['lang_hook'] != CAVE or CAVE + len(code) > CAVE_END: raise SystemExit(f'hook layout: {len(code):#x} bytes')
    return code, syms


def static_words(elf: Elf, code: bytes, syms: dict):
    if not (elf.word(0x3F7D68) in (0x13B000, GLYPHS * 288) and elf.word(0x141010) == 0x0C0400BC and elf.word(0x155CF8) == 0x0C0553EC):
        raise SystemExit('executable preimages drift (hook sites / font buffer)')
    if any(elf.get(CAVE, CAVE_END - CAVE)): raise SystemExit('hook cave not empty')
    elf.putw(0x3F7D68, GLYPHS * 288)
    elf.putw(0x141010, 0x0C000000 | CAVE >> 2)
    elf.putw(0x155CF8, 0x0C000000 | syms['title_hook'] >> 2)
    elf.put(CAVE, code)


def diff_records(a: Elf, b: Elf):
    recs = []
    for t, o, v, p, fs, ms, fl, al in a.loads:
        i = 0
        while i < fs:
            if a.b[o + i] == b.b[o + i]: i += 1; continue
            j = i
            while j < fs and (a.b[o + j] != b.b[o + j] or a.b[o + j:min(fs + o, o + j + 8)] != b.b[o + j:min(fs + o, o + j + 8)]): j += 1
            recs.append((v + i, bytes(b.b[o + i:o + j]))); i = j
    return recs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--sc', type=Path, required=True); p.add_argument('--tc', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True); p.add_argument('--receipt', type=Path)
    p.add_argument('--codebook', type=Path, default=ROOT / 'config/encoding/zh-release-font-assignments.json')
    p.add_argument('--tc-codebook', type=Path, required=True, help='the Traditional release codebook (message-box text)')
    p.add_argument('--work', type=Path, default=ROOT / 'build/zh-hant/assemble')
    a = p.parse_args()
    if a.out.resolve().parent != (ROOT / 'build/iso/test').resolve(): raise SystemExit('output must be under build/iso/test')
    sc, tc = Disc(a.sc), Disc(a.tc)
    exe_sc, exe_tc = Elf(sc.read(EXE)), Elf(tc.read(EXE))
    if exe_sc.loads != exe_tc.loads or len(exe_sc.b) != len(exe_tc.b): raise SystemExit('executable layouts differ')
    dmy, vt1m = sc.m['DMY/DMY.BIN'], sc.m['DATA/VT1.BIN']
    if dmy.extent_lba <= vt1m.extent_lba: raise SystemExit('DMY must follow VT1 (TC data is read through the VT1 handle)')
    rows = sc.vmap()
    report = {'identical_members': 0, 'copied_members': {}, 'vt1': {}}

    items, cur = [], dmy.extent_lba + 16
    def place(name, data):
        nonlocal cur
        lba = cur; items.append((name, lba, data)); cur += -(-len(data) // 2048); return lba

    # ---- members ----------------------------------------------------------------------------------------
    vmap_rows, copied = [], {}
    for name, e in sorted(tc.m.items()):
        if name in (EXE, 'DATA/VT1.BIN', 'DMY/DMY.BIN') or name not in sc.m: continue
        a_b, b_b = sc.read(name), tc.read(name)
        if a_b == b_b: report['identical_members'] += 1; continue
        if name.upper() not in rows: raise SystemExit(f'{name} differs but has no VMAP row')
        off, lba, sec = rows[name.upper()]
        if lba != sc.m[name].extent_lba: raise SystemExit(f'VMAP row of {name} does not match the ISO directory')
        tl = place(name, b_b); n = -(-len(b_b) // 2048)
        vmap_rows.append((off, tl, n)); copied[name] = b_b
        report['copied_members'][name] = {'sc_bytes': len(a_b), 'tc_bytes': len(b_b), 'tc_lba': tl, 'tc_sectors': n}
    for name in tc.m:
        if name not in sc.m: raise SystemExit(f'TC build has an extra member {name}')

    # ---- VT1: font chunk, stage-title group ------------------------------------------------------------
    v_sc, v_tc = sc.read('DATA/VT1.BIN'), tc.read('DATA/VT1.BIN')
    o_sc = read_executable_archive_offsets(bytes(exe_sc.b), CORE_ARCHIVE_SPECS['VT1.BIN'], len(v_sc))
    o_tc = read_executable_archive_offsets(bytes(exe_tc.b), CORE_ARCHIVE_SPECS['VT1.BIN'], len(v_tc))
    chunk = lambda v, o, i: v[o[i]:o[i + 1]]
    same_chunk = lambda i: chunk(v_sc, o_sc, i).rstrip(b'\0') == chunk(v_tc, o_tc, i).rstrip(b'\0')   # slot padding moves
    from srwz.codec import decode
    font = chunk(v_tc, o_tc, FONT_CHUNK)                  # the Traditional build's own font, as built
    tc_glyphs = decode(font).output
    if len(tc_glyphs) % 288 or len(tc_glyphs) > GLYPHS * 288: raise SystemExit('TC font exceeds the fixed font buffer')
    font_report = {'glyphs': len(tc_glyphs) // 288}
    font_lba = place('TC font (VT1 chunk 2)', font)
    font_offset = (font_lba - vt1m.extent_lba) * 2048
    title_shift = None
    menu_chunk = menu_bytes = None                          # (VT1-relative offset, size) of the TC title-menu chunk
    for i in range(len(o_sc) - 1):
        if i == FONT_CHUNK or same_chunk(i): continue
        if i == TITLE_GROUP:
            g = chunk(v_tc, o_tc, i); glba = place('TC stage-title group (VT1 chunk 8)', g)
            title_shift = (glba - vt1m.extent_lba) * 2048 - o_sc[i]
        elif i == MENU_CHUNK:
            menu_bytes = chunk(v_tc, o_tc, i).rstrip(b'\0'); glba = place('TC title menu (VT1 chunk 6)', menu_bytes)
            menu_chunk = ((glba - vt1m.extent_lba) * 2048, len(menu_bytes))
        else:
            raise SystemExit(f'VT1 chunk {i} differs and has no Traditional loader')
    report['vt1'] = {'font_bytes': len(font), 'font': font_report, 'sc_font_bytes': o_sc[FONT_CHUNK + 1] - o_sc[FONT_CHUNK],
                     'font_vt1_relative_offset': font_offset, 'title_group_shift': title_shift,
                     'title_menu_chunk': menu_chunk}

    # ---- executables ------------------------------------------------------------------------------------
    tc_exe = Elf(bytes(exe_tc.b))
    tc_exe.put(VT1_TABLE, exe_sc.get(VT1_TABLE, 15 * 4))          # disc keeps the SC VT1
    for va, w in FONT_LOADER.items():
        if tc_exe.word(va) != w: raise SystemExit(f'font loader preimage drift at {va:#x}')
    lui = lambda rt, v: 0x3C000000 | rt << 16 | v
    ori = lambda rt, v: 0x34000000 | rt << 21 | rt << 16 | v
    for va, w in [(0x13A174, lui(6, len(font) >> 16)), (0x13A184, ori(6, len(font) & 0xFFFF)),
                  (0x13A19C, lui(5, font_offset >> 16)), (0x13A1A0, ori(5, font_offset & 0xFFFF)), (0x13A1A8, 0),
                  (0x13A95C, 0x10000002), (0x13A960, 0x90240061)]:
        tc_exe.putw(va, w)
    if menu_chunk is not None:
        # The title screen reads chunk 6 at 0x154C8C-0x154CB0: a1 = table[hw 0x3F8668], v0 = table[that + 1],
        # 0x139620(VT1 handle, a1, v0 - a1). Load the DMY offset and its end as immediates instead (the read
        # routine does not clip at the file end, as for the font).
        for va, w in MENU_LOADER.items():
            if tc_exe.word(va) != w: raise SystemExit(f'title-menu loader preimage drift at {va:#x}')
        start, size = menu_chunk; end = start + size
        for va, w in [(0x154C8C, lui(5, start >> 16)), (0x154C90, ori(5, start & 0xFFFF)),
                      (0x154C98, lui(2, end >> 16)), (0x154CA0, ori(2, end & 0xFFFF)),
                      (0x154CA4, 0), (0x154CA8, 0)]:
            tc_exe.putw(va, w)
    if title_shift is not None:
        inner = struct.unpack('<%dI' % TITLE_COUNT, tc_exe.get(TITLE_TABLE, TITLE_COUNT * 4))
        if inner[0] != 0: raise SystemExit('TC title table does not start at 0')
        tc_exe.put(TITLE_TABLE, struct.pack('<%dI' % TITLE_COUNT, *(title_shift + x for x in inner)))

    def build_patch(code, syms):
        s, t = Elf(bytes(exe_sc.b)), Elf(bytes(tc_exe.b))
        static_words(s, code, syms); static_words(t, code, syms)
        recs = diff_records(s, t)
        body = b''.join(struct.pack('<3I', *r) for r in vmap_rows)
        for va, data in recs:
            if not data or any(va < e and st < va + len(data) for st, e in FORBIDDEN): raise SystemExit(f'patch record in a forbidden range: {va:#x}')
            body += struct.pack('<2I', va, len(data)) + data + bytes(-len(data) % 4)
        head = struct.pack('<4s5I', b'ZHTP', 1, len(vmap_rows), len(recs), len(body), sum(struct.unpack(f'<{len(body) // 4}I', body)) & 0xFFFFFFFF)
        return s, t, recs, head + bytes(32 - len(head)) + body

    codebooks = {'sc': a.codebook, 'tc': a.tc_codebook}
    options = options_address(exe_sc, exe_tc)
    code0, syms0 = assemble_hook(a.work, 0, 1, codebooks, options)
    _, _, recs, pf = build_patch(code0, syms0)
    patch_sectors = -(-len(pf) // 2048)
    if patch_sectors * 2048 > SCRATCH_MAX: raise SystemExit('patch file exceeds the scratch buffer')
    patch_lba = place('patch file', pf)
    code, syms = assemble_hook(a.work, patch_lba, patch_sectors, codebooks, options)
    SC, TC, recs2, pf2 = build_patch(code, syms)
    if recs2 != recs or pf2 != pf: raise SystemExit('patch depends on the hook bytes')
    replay = Elf(bytes(SC.b)); body = pf[32:]; nv, nr = struct.unpack_from('<2I', pf, 8); q = nv * 12
    for _ in range(nr):
        va, n = struct.unpack_from('<2I', body, q); q += 8; replay.put(va, body[q:q + n]); q += n + (-n % 4)
    if replay.b != TC.b: raise SystemExit('patch replay differs from the TC executable')
    if cur > dmy.extent_lba + dmy.size // 2048: raise SystemExit('DMY is full')

    # ---- write and read back ----------------------------------------------------------------------------
    if a.out.exists(): a.out.unlink()
    subprocess.run(['cp', '-c', str(a.sc), str(a.out)], check=True)
    exe_e = sc.m[EXE]; spans = []
    with open(a.out, 'r+b') as f:
        f.seek(dmy.extent_lba * 2048)
        if any(f.read((cur - dmy.extent_lba) * 2048)): raise SystemExit('DMY area not empty')
        for name, lba, data in items:
            n = -(-len(data) // 2048) * 2048
            f.seek(lba * 2048); f.write(data + bytes(n - len(data))); spans.append((lba * 2048, lba * 2048 + n))
        f.seek(exe_e.extent_lba * 2048); f.write(SC.b); spans.append((exe_e.extent_lba * 2048, exe_e.extent_lba * 2048 + len(SC.b)))
    with open(a.out, 'rb') as f:
        def at(off, n): f.seek(off); return f.read(n)
        for off, lba, n in vmap_rows:
            name = next(k for k, v in report['copied_members'].items() if v['tc_lba'] == lba)
            if at(lba * 2048, len(copied[name])) != copied[name]: raise SystemExit(f'readback {name}')
        if at(vt1m.extent_lba * 2048 + font_offset, len(font)) != font: raise SystemExit('readback font')
        if menu_chunk is not None and at(vt1m.extent_lba * 2048 + menu_chunk[0], menu_chunk[1]) != menu_bytes:
            raise SystemExit('readback title menu')
        if title_shift is not None:
            inner = struct.unpack('<%dI' % TITLE_COUNT, TC.get(TITLE_TABLE, TITLE_COUNT * 4))
            base = vt1m.extent_lba * 2048 + o_sc[TITLE_GROUP]
            if at(base + inner[0], inner[-1] - inner[0]) != chunk(v_tc, o_tc, TITLE_GROUP): raise SystemExit('readback titles')
    spans.sort(); pos = 0
    with open(a.sc, 'rb') as x, open(a.out, 'rb') as y:
        size = x.seek(0, 2)
        if size != y.seek(0, 2): raise SystemExit('image size changed')
        for st, e in spans + [(size, size)]:
            x.seek(pos); y.seek(pos); n = st - pos
            while n > 0:
                k = min(n, 64 << 20)
                if x.read(k) != y.read(k): raise SystemExit('bytes outside the written spans changed')
                n -= k
            pos = e
    receipt = {'sc_iso': str(a.sc), 'tc_iso': str(a.tc), 'iso': str(a.out), 'sc_iso_sha256_head': None,
               'hook_bytes': len(code), 'dmy': [{'item': n, 'lba': l, 'bytes': len(d)} for n, l, d in items],
               'dmy_used_bytes': (cur - dmy.extent_lba) * 2048, 'dmy_bytes': dmy.size,
               'patch': {'lba': patch_lba, 'sectors': patch_sectors, 'bytes': len(pf), 'vmap_rows': len(vmap_rows),
                         'records': len(recs), 'record_bytes': sum(len(d) for _, d in recs)},
               'sc_exe_sha256': sha(SC.b), 'tc_exe_sha256': sha(TC.b), **report}
    path = a.receipt or a.out.with_suffix('.receipt.json')
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({k: receipt[k] for k in ('hook_bytes', 'patch', 'dmy_used_bytes', 'copied_members', 'vt1')}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
