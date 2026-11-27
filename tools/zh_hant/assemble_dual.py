#!/usr/bin/env python3
"""Assemble one disc holding Simplified and Traditional from single-language builds (--edition original | best | sp).

The addresses named below are the Original's; BEST's and SP's are in editions.py.

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
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from special_disc.resource_view import ResourceView
from srwz.file_identity import sha256_file
from srwz.font import LINEAR_GLYPH_FALLBACK
from srwz.iso9660 import scan_iso9660, member_map  # noqa: E402
from editions import EDITIONS, edition_inc, paths_inc  # noqa: E402

ED = EDITIONS['original']                # set by --edition (main)
EXE = ED.exe
CAVE, CAVE_END = ED.cave
SCRATCH, SCRATCH_MAX = 0x1C00000, 0x80000
GLYPHS = 4992                            # font buffer sized once for both languages (Traditional profile: 4,992)
FONT_CHUNK, TITLE_GROUP, MENU_CHUNK = 2, 8, 6     # main game (Original, BEST): addresses in editions.Edition.main
TITLE_COUNT, VT1_CHUNKS = 117, 15
SP_VT1_TABLE, SP_FONT_CHUNK, SP_FONT_DONOR, SP_VT1_TAIL = 0x452E10, 3, 1, 37   # SP: font chunk 3 (chunk 1 donates its
                                                         # zero tail when a bigger font is installed), tail groups 37..
SP_FONT_BUFFER = 0x4524E8
SP_TITLE_GROUP, SP_TITLE_TABLE = 9, 0x475A60
SP_FONT_LOADER = {0x13AC14: 0x84232DE4, 0x13AC24: 0x84222DE6, 0x13AC3C: 0x8C650000, 0x13AC40: 0x8C420000,
                  0x13AC48: 0x00453023, 0x13B3FC: 0x1000000C, 0x13B400: 0xA4200062}
# Settings-panel text, per display language (each encoded with that language's codebook). MSG_KEYS is the
# order lang_hook.S indexes (pick_msg); the panel line is cursor/blank + label + value, the values come in pairs
# (setting 0 / 1; the language row adds v_hk as value 2 on three-language discs). The selected row starts with ⇒
# (stock 0x81CB). The box centres every line by its code count (0x139B00: font 6 counts 16 for every code, blanks
# included), so all three rows have the same code count (labels 5 codes, padded on the left if shorter; values padded
# on the right: 4 codes on a two-language disc, 6 with the regional language names) and line up as a column with the
# colons aligned. The hint row reserves spaces for the native D-pad, circle and cross sprites.
# Identical fragments are stored once.
MSG_KEYS = ['cursor', 'blank', 'lbl_lang', 'lbl_zero', 'lbl_quote', 'v_sc', 'v_tc', 'v_dot', 'v_plain', 'v_cn', 'v_jp',
            'hint', 'ok', 'fail', 'nl', 'v_hk']
# The zero row shows the two zeros themselves: U+E000 / U+E001 stand for the Latin bank's dotted zero (code
# 0x8440, slot 0) and plain zero (0x844A, slot 10); the message box draws those codes' glyphs directly.
_BASE = {
    'sc': {'cursor': '⇒', 'blank': '　', 'lbl_lang': '游戏语言：', 'lbl_zero': '数字样式：', 'lbl_quote': '对话引号：',
           'v_sc': '简体中文', 'v_tc': '繁体中文', 'v_dot': '\ue000', 'v_plain': '\ue001', 'v_cn': '中文“”', 'v_jp': '日文「」',
           'hint': '　　左右切换　　　保存　　　取消', 'ok': '设定已保存。\n（语言在重新启动游戏后生效）', 'fail': '无法写入记忆卡。', 'nl': '\n',
           'v_tw': '台湾繁体', 'v_hk': '香港繁体'},
    'tc': {'cursor': '⇒', 'blank': '　', 'lbl_lang': '遊戲語言：', 'lbl_zero': '數字樣式：', 'lbl_quote': '對話引號：',
           'v_sc': '簡體中文', 'v_tc': '繁體中文', 'v_dot': '\ue000', 'v_plain': '\ue001', 'v_cn': '中文“”', 'v_jp': '日文「」',
           'hint': '　　左右切換　　　保存　　　取消', 'ok': '設定已保存。\n（語言在重新啟動遊戲後生效）', 'fail': '無法寫入記憶卡。', 'nl': '\n',
           'v_tw': '台灣繁體', 'v_hk': '香港繁體'},
    'hk': {'cursor': '⇒', 'blank': '　', 'lbl_lang': '遊戲語言：', 'lbl_zero': '數字樣式：', 'lbl_quote': '對話引號：',
           'v_sc': '簡體中文', 'v_tc': '繁體中文', 'v_dot': '\ue000', 'v_plain': '\ue001', 'v_cn': '中文“”', 'v_jp': '日文「」',
           'hint': '　　左右切換　　　保存　　　取消', 'ok': '設定已保存。\n（語言在重新啓動遊戲後生效）', 'fail': '無法寫入記憶卡。', 'nl': '\n',
           'v_tw': '台灣繁體', 'v_hk': '香港繁體'},
}


def panel_messages(langs: int) -> dict:
    """Panel fragments per display language for a disc with `langs` languages (2: SC / TC, 3: SC / Taiwan / Hong Kong).
    Hong Kong shows the Taiwan panel text (lang_hook.pick_msg), so a three-language disc still has two text sets."""
    out = {}
    for lang in ('sc', 'tc'):
        m = dict(_BASE[lang])
        if langs == 3: m['v_tc'] = m['v_tw']
        else: m['v_hk'] = ''
        for k in ('v_sc', 'v_tc', 'v_dot', 'v_plain', 'v_cn', 'v_jp', 'v_hk'):
            if m[k]: m[k] = m[k] + '　' * (4 - len(m[k]))
        rows = [(m[l], vs) for l, vs in (('lbl_lang', [m['v_sc'], m['v_tc']] + ([m['v_hk']] if langs == 3 else [])),
                                          ('lbl_zero', [m['v_dot'], m['v_plain']]), ('lbl_quote', [m['v_cn'], m['v_jp']]))]
        assert {1 + len(l) + len(v) for l, vs in rows for v in vs} == {10}, 'panel rows must be 10 codes'
        assert 3 * (2 * 10 + 1) + 2 * len(m['hint']) + 1 <= 96, 'panel text exceeds panel_buf'
        out[lang] = {k: m[k] for k in MSG_KEYS}
    return out


MESSAGES = panel_messages(2)                     # set for the disc being assembled (main)
STOCK_CODES = {'０': '824F', '　': '8140', '：': '8146', '⇒': '81CB', '\ue000': '8440', '\ue001': '844A'}   # stock full-width codes the release codebooks do not list
OPTIONS_MARKER = b'SRWZOPT1'                              # srwz.proportional_hooks.DISPLAY_OPTIONS_MARKER


def vt1_offsets(elf, size: int) -> tuple:
    """The main game's VT1 chunk offsets from the executable's table, closed by the archive size."""
    offsets = struct.unpack(f'<{VT1_CHUNKS}I', elf.get(ED.main['vt1_table'], VT1_CHUNKS * 4))
    if offsets[0] != 0 or any(x >= y for x, y in zip(offsets, offsets[1:])) or offsets[-1] > size:
        raise SystemExit('VT1 offset table is not the expected table')
    return offsets + ((size,) if offsets[-1] < size else ())


def forbidden():
    return [(CAVE, CAVE_END), (ED.boot_site[0], ED.boot_site[0] + 8), (ED.title_site[0], ED.title_site[0] + 4),
            *ED.forbidden]
sha = lambda b: hashlib.sha256(b).hexdigest()


class Disc:
    def __init__(self, path: Path):
        self.path = path; self.m = member_map(scan_iso9660(path))

    def read(self, name: str) -> bytes:
        e = self.m[name]
        with self.path.open('rb') as f:
            f.seek(e.extent_lba * 2048); return f.read(e.size)

    def vmap(self) -> dict:
        with self.path.open('rb') as f:
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


def assemble_hook(work: Path, patches: list, codebooks: dict, options: int):
    """patches: [(lba, sectors)] per Traditional variant (Taiwan, then Hong Kong on a three-language disc)."""
    work.mkdir(parents=True, exist_ok=True)
    (p1, n1), (p2, n2) = patches[0], patches[-1]
    langs = 1 + len(patches)
    (work / 'params.inc').write_text(f'        .equ PATCH_LBA, {p1:#x}\n        .equ PATCH_SECTORS, {n1}\n'
                                     f'        .equ PATCH2_LBA, {p2:#x}\n        .equ PATCH2_SECTORS, {n2}\n'
                                     f'        .equ PATCH_MAX, {max(n1, n2)}\n        .equ LANGS, {langs}\n'
                                     f'        .equ SCRATCH, {SCRATCH:#x}\n        .equ OPTIONS, {options:#x}\n'
                                     f'        .equ RUNTIME_BUF, {ED.runtime_buf:#x}\n')
    (work / 'messages.inc').write_text(codebook_messages(codebooks))
    (work / 'edition.inc').write_text(edition_inc(ED))
    (work / 'paths.inc').write_text(paths_inc(ED))
    title = ED.icon_title.encode('shift_jis'); assert len(title) <= 64
    (work / 'icon_title.inc').write_text('icon_title:  # card browser title (Shift-JIS, line 2 from byte 22)\n        .byte '
                                         + ', '.join(str(x) for x in title + bytes(64 - len(title))) + '\n')
    def tool(t, *a, out=False):
        r = subprocess.run(['mipsel-linux-gnu-' + t, *a], check=True, capture_output=True, text=True); return r.stdout
    tool('as', '-EL', '-mips3', '-mabi=o64', '-I', str(work), '-o', str(work / 'hook.o'), str(Path(__file__).with_name('lang_hook.S')))
    tool('ld', '-EL', f'-Ttext={CAVE:#x}', '-e', 'lang_hook', '-o', str(work / 'hook.elf'), str(work / 'hook.o'))
    tool('objcopy', '-O', 'binary', '-j', '.text', str(work / 'hook.elf'), str(work / 'hook.bin'))
    (work / 'hook.o').unlink()
    dis = re.split(r'<hook_data>:', tool('objdump', '-d', str(work / 'hook.elf')))[0]   # code only
    if ' $at' in dis or ',at' in dis or '\tat,' in dis: raise SystemExit('assembler expanded a macro through $at')
    syms = tool('nm', str(work / 'hook.elf')); (work / 'symbols.txt').write_text(syms)
    syms = {l.split()[2]: int(l.split()[0], 16) for l in syms.splitlines() if len(l.split()) == 3}
    code = (work / 'hook.bin').read_bytes()
    if syms['lang_hook'] != CAVE or CAVE + len(code) > CAVE_END: raise SystemExit(f'hook layout: {len(code):#x} bytes')
    return code, syms


def verify_main_font_loader(elf: Elf, sites: list) -> None:
    """Single-language donors use VT1 table loads, with either stock or linear glyph lookup."""
    for va, word in sites[:-2]:
        if elf.word(va) != word:
            raise SystemExit(f'font loader preimage drift at {va:#x}')
    fallback = tuple(elf.word(va) for va, _ in sites[-2:])
    if fallback not in (tuple(word for _, word in sites[-2:]), LINEAR_GLYPH_FALLBACK):
        raise SystemExit('font loader glyph fallback preimage drift')


def static_words(elf: Elf, code: bytes, syms: dict):
    (boot, boot_word), (title, title_word) = ED.boot_site, ED.title_site
    if not (elf.word(boot) == boot_word and elf.word(title) == title_word):
        raise SystemExit('executable preimages drift (hook sites)')
    if ED.main:
        buffer = ED.main['font_buffer']
        # A single-language donor holds the stock size, this disc's size, or its own configured linear capacity.
        donor = json.loads((ROOT / 'config/fonts/zh-release-font.json').read_text(encoding='utf-8'))
        donor_glyphs = (donor.get('font_capacity') or {}).get('glyph_count', 0)
        if donor_glyphs > GLYPHS: raise SystemExit('single-language font exceeds the multi-language font buffer')
        if elf.word(buffer) not in (0x13B000, GLYPHS * 288, donor_glyphs * 288):
            raise SystemExit('executable preimage drift (font buffer)')
        elf.putw(buffer, GLYPHS * 288)
    if any(elf.get(CAVE, CAVE_END - CAVE)): raise SystemExit('hook cave not empty')
    elf.putw(boot, 0x0C000000 | CAVE >> 2)
    elf.putw(title, 0x0C000000 | syms['title_hook'] >> 2)
    elf.put(CAVE, code)


def add_cave_segment(data: bytes) -> bytes:
    """SP: the hook cave lies above the stock image end with no file data behind it. Append a zero-filled,
    page-aligned PT_LOAD for it in the spare program-header slot (both languages get the same layout)."""
    b = bytearray(data)
    ph, n = struct.unpack_from('<I', b, 28)[0], struct.unpack_from('<H', b, 44)[0]
    hs = [struct.unpack_from('<8I', b, ph + 32 * i) for i in range(n)]
    if any(t == 1 and v < CAVE_END and CAVE < v + ms for t, o, v, p, fs, ms, fl, al in hs):
        raise SystemExit('hook cave overlaps a loaded segment')
    first = min(o for t, o, v, p, fs, ms, fl, al in hs if fs)
    if ph + (n + 1) * 32 > first or any(b[ph + n * 32:ph + (n + 1) * 32]): raise SystemExit('no free program header slot')
    off = (len(b) + 4095) & ~4095
    b += bytes(off - len(b)) + bytes(CAVE_END - CAVE)
    struct.pack_into('<8I', b, ph + n * 32, 1, off, CAVE, CAVE, CAVE_END - CAVE, CAVE_END - CAVE, 7, 16)
    struct.pack_into('<H', b, 44, n + 1)
    return bytes(b)


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
    p.add_argument('--hk', type=Path, help='Traditional (Hong Kong) build of the same pipeline: a three-language disc '
                                           '(language 1 = --tc as Taiwan, language 2 = --hk)')
    p.add_argument('--out', type=Path, required=True); p.add_argument('--receipt', type=Path)
    p.add_argument('--codebook', type=Path, default=ROOT / 'config/encoding/zh-release-font-assignments.json')
    p.add_argument('--tc-codebook', type=Path, required=True, help='the Traditional release codebook (message-box text)')
    p.add_argument('--work', type=Path, default=ROOT / 'build/zh-hant/assemble')
    p.add_argument('--edition', choices=sorted(EDITIONS), default='original')
    p.add_argument('--builtin-cheats', action='store_true', help='install the in-game cheat menu')
    a = p.parse_args()
    if not a.out.resolve().parent.is_relative_to((ROOT / 'build/iso/test').resolve()): raise SystemExit('output must be under build/iso/test')
    receipt = a.receipt or a.out.with_suffix('.receipt.json')
    if receipt.resolve() in {p.resolve() for p in (a.out, a.sc, a.tc, a.hk) if p}:
        raise SystemExit('receipt aliases a disc')
    if a.out.resolve() in {p.resolve() for p in (a.sc, a.tc, a.hk) if p}:
        raise SystemExit('output aliases an input disc')
    with tempfile.TemporaryDirectory(dir=a.out.parent) as image_dir, tempfile.TemporaryDirectory(dir=receipt.parent) as receipt_dir:
        staged = Path(image_dir) / 'verified.iso'
        staged_receipt = Path(receipt_dir) / 'verified.json'
        assemble(a, staged, staged_receipt)
        publish(staged, a.out, staged_receipt, receipt)


def publish(staged: Path, output: Path, staged_receipt: Path, receipt: Path) -> None:
    previous_image = staged.parent / 'previous.iso'
    previous_receipt = staged_receipt.parent / 'previous.json'
    if output.exists():
        os.link(output, previous_image)
    if receipt.exists():
        receipt.replace(previous_receipt)
    try:
        staged.replace(output)
        try:
            staged_receipt.replace(receipt)
        except OSError:
            if previous_image.exists():
                previous_image.replace(output)
            else:
                output.unlink()
            raise
    except OSError:
        if previous_receipt.exists():
            previous_receipt.replace(receipt)
        raise


def disc_identity(disc):
    """Identify the logical ISO bytes, including SP's sparse resource views."""
    digest = disc.digest() if isinstance(disc, ResourceView) else sha256_file(disc)
    return {"size": disc.stat().st_size, "sha256": digest}


def assemble(a, staged: Path, staged_receipt: Path) -> None:
    global ED, EXE, CAVE, CAVE_END, MESSAGES
    ED = EDITIONS[a.edition]; EXE = ED.exe; CAVE, CAVE_END = ED.cave
    sc = Disc(a.sc)
    discs = [('tc', Disc(a.tc))] + ([('hk', Disc(a.hk))] if a.hk else [])
    langs = 1 + len(discs)
    MESSAGES = panel_messages(langs)
    load_exe = (lambda d: Elf(add_cave_segment(d.read(EXE)))) if ED.key == 'sp' else (lambda d: Elf(d.read(EXE)))
    exe_sc = load_exe(sc)
    dmy, vt1m = sc.m['DMY/DMY.BIN'], sc.m['DATA/VT1.BIN']
    if dmy.extent_lba <= vt1m.extent_lba: raise SystemExit('DMY must follow VT1 (TC data is read through the VT1 handle)')
    rows = sc.vmap()

    tail_items = []
    tail_lba = a.sc.stat().st_size // 2048
    items, cur = [], dmy.extent_lba + 16
    placed, tail_placed = {}, {}
    def place(name, data):
        """Copy data into DMY once; a variant whose bytes equal an earlier copy shares it."""
        nonlocal cur
        k = sha(data)
        if k in placed: return placed[k]
        lba = cur; items.append((name, lba, data)); cur += -(-len(data) // 2048); placed[k] = lba; return lba
    def place_tail(name, data):
        nonlocal tail_lba
        k = sha(data)
        if k in tail_placed: return tail_placed[k]
        lba = tail_lba; tail_items.append((name, lba, data)); tail_lba += -(-len(data) // 2048); tail_placed[k] = lba
        return lba

    def variant(tag, tc):
        """Members, VT1 and executable of one Traditional variant against the Simplified disc."""
        V = {'tag': tag, 'report': {'identical_members': 0, 'copied_members': {}, 'vt1': {}}, 'vmap_rows': [], 'copied': {},
             'font': None, 'font_offset': None, 'menu_chunk': None, 'menu_bytes': None, 'title_shift': None,
             'vt1_tail_lba': None}
        report, vmap_rows, copied = V['report'], V['vmap_rows'], V['copied']
        label = (lambda s: s) if tag == 'tc' else (lambda s: f'HK {s}')
        exe_tc = load_exe(tc)
        if exe_sc.loads != exe_tc.loads or len(exe_sc.b) != len(exe_tc.b): raise SystemExit(f'{tag}: executable layouts differ')
        # ---- members ------------------------------------------------------------------------------------
        # A member only one build has would otherwise ship as the Simplified one (missing) or not at all (extra).
        extra, missing = sorted(set(tc.m) - set(sc.m)), sorted(set(sc.m) - set(tc.m))
        if extra or missing:
            raise SystemExit(f'{tag} build member set differs from Simplified: extra {extra}, missing {missing}')
        for name, e in sorted(tc.m.items()):
            if name in (EXE, 'DATA/VT1.BIN', 'DMY/DMY.BIN') or name not in sc.m: continue
            if e.size == sc.m[name].size and e.size > 256 << 20:
                with sc.path.open('rb') as left, tc.path.open('rb') as right:
                    left.seek(sc.m[name].extent_lba * 2048)
                    right.seek(e.extent_lba * 2048)
                    if all(left.read(min(8 << 20, e.size-at)) == right.read(min(8 << 20, e.size-at))
                           for at in range(0, e.size, 8 << 20)):
                        report['identical_members'] += 1
                        continue
            a_b, b_b = sc.read(name), tc.read(name)
            if a_b == b_b: report['identical_members'] += 1; continue
            if ED.key == 'sp' and name == 'VMAP.DAT':
                # The single-language gallery build relocates archives. Check that
                # these bytes only describe the two input discs' own ISO extents.
                expected = bytearray(a_b)
                for member, (offset, lba, sectors) in rows.items():
                    sc_entry, tc_entry = sc.m[member], tc.m[member]
                    if (sc_entry.extent_lba, sc_entry.size) == (tc_entry.extent_lba, tc_entry.size):
                        continue
                    if (lba, sectors) != (sc_entry.extent_lba, -(-sc_entry.size // 2048)):
                        raise SystemExit(f'SP VMAP source allocation drift: {member}')
                    struct.pack_into('<II', expected, offset + 40, tc_entry.extent_lba, -(-tc_entry.size // 2048))
                if expected != b_b: raise SystemExit(f'{tag}: unexpected SP VMAP differences')
                continue
            if name.upper() not in rows: raise SystemExit(f'{name} differs but has no VMAP row')
            off, lba, sec = rows[name.upper()]
            if lba != sc.m[name].extent_lba: raise SystemExit(f'VMAP row of {name} does not match the ISO directory')
            n = -(-len(b_b) // 2048)
            # The Traditional theatre artwork changes the whole AID archive. Like VT1,
            # it is read through VMAP and exceeds the space left in the SP dummy member.
            if ((ED.key == 'sp' and name == 'AID_DATA/AIDDATA.BIN') or
                    (tag == 'hk' and name == 'MAP/MAPMODEL.BIN' and sha(b_b) not in placed)):
                tl = place_tail(label(name), b_b)
            else:
                tl = place(label(name), b_b)
            vmap_rows.append((off, tl, n)); copied[name] = b_b
            report['copied_members'][name] = {'sc_bytes': len(a_b), 'tc_bytes': len(b_b), 'tc_lba': tl, 'tc_sectors': n}

        # ---- VT1: font chunk, stage-title group ---------------------------------------------------------
        v_sc, v_tc = sc.read('DATA/VT1.BIN'), tc.read('DATA/VT1.BIN')
        V['v_tc'] = v_tc
        tc_exe = Elf(bytes(exe_tc.b))
        appended_vt1 = None
        if ED.main:
            o_sc, o_tc = vt1_offsets(exe_sc, len(v_sc)), vt1_offsets(exe_tc, len(v_tc))
            V['o_sc'], V['o_tc'] = o_sc, o_tc
            chunk = lambda v, o, i: v[o[i]:o[i + 1]]
            same_chunk = lambda i: chunk(v_sc, o_sc, i).rstrip(b'\0') == chunk(v_tc, o_tc, i).rstrip(b'\0')   # slot padding moves
            from srwz.codec import decode
            font = chunk(v_tc, o_tc, FONT_CHUNK)                  # the Traditional build's own font, as built
            tc_glyphs = decode(font).output
            if len(tc_glyphs) % 288 or len(tc_glyphs) > GLYPHS * 288: raise SystemExit('TC font exceeds the fixed font buffer')
            font_report = {'glyphs': len(tc_glyphs) // 288}
            font_lba = place(label('TC font (VT1 chunk 2)'), font)
            font_offset = (font_lba - vt1m.extent_lba) * 2048
            title_shift = None
            menu_chunk = menu_bytes = None                          # (VT1-relative offset, size) of the TC title-menu chunk
            for i in range(len(o_sc) - 1):
                if i == FONT_CHUNK or same_chunk(i): continue
                if i == TITLE_GROUP:
                    g = chunk(v_tc, o_tc, i); glba = place(label('TC stage-title group (VT1 chunk 8)'), g)
                    title_shift = (glba - vt1m.extent_lba) * 2048 - o_sc[i]
                elif i == MENU_CHUNK:
                    menu_bytes = chunk(v_tc, o_tc, i).rstrip(b'\0'); glba = place(label('TC title menu (VT1 chunk 6)'), menu_bytes)
                    menu_chunk = ((glba - vt1m.extent_lba) * 2048, len(menu_bytes))
                else:
                    raise SystemExit(f'VT1 chunk {i} differs and has no Traditional loader')
            V.update(font=font, font_offset=font_offset, menu_chunk=menu_chunk, menu_bytes=menu_bytes, title_shift=title_shift)
            report['vt1'] = {'font_bytes': len(font), 'font': font_report, 'sc_font_bytes': o_sc[FONT_CHUNK + 1] - o_sc[FONT_CHUNK],
                             'font_vt1_relative_offset': font_offset, 'title_group_shift': title_shift,
                             'title_menu_chunk': menu_chunk}

            # ---- executable ------------------------------------------------------------------------------
            vt1_table = ED.main['vt1_table']
            tc_exe.put(vt1_table, exe_sc.get(vt1_table, VT1_CHUNKS * 4))  # disc keeps the SC VT1
            verify_main_font_loader(tc_exe, ED.main['font_loader'])
            lui = lambda rt, v: 0x3C000000 | rt << 16 | v
            ori = lambda rt, v: 0x34000000 | rt << 21 | rt << 16 | v
            sites = [va for va, _ in ED.main['font_loader']]
            for va, w in zip(sites, [lui(6, len(font) >> 16), ori(6, len(font) & 0xFFFF),
                                     lui(5, font_offset >> 16), ori(5, font_offset & 0xFFFF), 0,
                                     *LINEAR_GLYPH_FALLBACK]):
                tc_exe.putw(va, w)
            if menu_chunk is not None:
                # The title screen reads chunk 6 at 0x154C8C-0x154CB0: a1 = table[hw 0x3F8668], v0 = table[that + 1],
                # 0x139620(VT1 handle, a1, v0 - a1). Load the DMY offset and its end as immediates instead (the read
                # routine does not clip at the file end, as for the font).
                for va, w in ED.main['menu_loader']:
                    if tc_exe.word(va) != w: raise SystemExit(f'title-menu loader preimage drift at {va:#x}')
                start, size = menu_chunk; end = start + size
                sites = [va for va, _ in ED.main['menu_loader']]
                for va, w in zip(sites, [lui(5, start >> 16), ori(5, start & 0xFFFF),
                                         lui(2, end >> 16), ori(2, end & 0xFFFF), 0, 0]):
                    tc_exe.putw(va, w)
            if title_shift is not None:
                title_table = ED.main['title_table']
                inner = struct.unpack('<%dI' % TITLE_COUNT, tc_exe.get(title_table, TITLE_COUNT * 4))
                if inner[0] != 0: raise SystemExit('TC title table does not start at 0')
                tc_exe.put(title_table, struct.pack('<%dI' % TITLE_COUNT, *(title_shift + x for x in inner)))
        elif ED.key == 'sp' and v_sc != v_tc:
            # SP: VT1 is read in groups whose length is the next group's start in one offset table, so no single chunk
            # can be moved without breaking its neighbour. In Traditional mode the whole VT1 member is redirected (VMAP
            # row) to a complete Traditional copy appended after the image; the TC executable keeps its own VT1 table,
            # and only the font buffer grows (Traditional mode only: the hook runs before the font is loaded).
            vt1_row = rows.get('DATA/VT1.BIN')
            if vt1_row is None or vt1_row[1] != vt1m.extent_lba: raise SystemExit('SP VT1 VMAP row missing or stale')
            from srwz.codec import decode
            def sp_table(elf, size):
                out, va = [], SP_VT1_TABLE
                while True:
                    x = elf.word(va); out.append(x); va += 4
                    if x == size: return out
            o_tc = sp_table(exe_tc, len(v_tc))
            tc_glyphs = decode(v_tc[o_tc[SP_FONT_CHUNK]:o_tc[SP_FONT_CHUNK + 1]]).output
            if len(tc_glyphs) % 288 or len(tc_glyphs) > GLYPHS * 288: raise SystemExit('TC font exceeds the font buffer')
            from special_disc.writeback.install_font import configure_font_loader
            configure_font_loader(tc_exe.b, len(tc_glyphs))
            appended_vt1 = v_tc
            report['vt1'] = {'redirect': 'whole member appended after the image', 'bytes': len(v_tc),
                             'font': {'glyphs': len(tc_glyphs) // 288}}
        elif v_sc != v_tc:
            raise SystemExit(f'{ED.key}: VT1 differs and the Traditional VT1 loaders are not implemented yet')
        else:
            report['vt1'] = {'identical': True}
        if appended_vt1 is not None:
            V['vt1_tail_lba'] = place_tail(label('DATA/VT1.BIN'), appended_vt1)  # written at the image end
            vmap_rows.append((rows['DATA/VT1.BIN'][0], V['vt1_tail_lba'], -(-len(appended_vt1) // 2048)))
            report['vt1']['lba'] = V['vt1_tail_lba']
        V['exe'] = tc_exe
        return V

    VS = [variant(tag, d) for tag, d in discs]

    def build_patch(code, syms, V):
        s, t = Elf(bytes(exe_sc.b)), Elf(bytes(V['exe'].b))
        static_words(s, code, syms); static_words(t, code, syms)
        recs = diff_records(s, t)
        body = b''.join(struct.pack('<3I', *r) for r in V['vmap_rows'])
        for va, data in recs:
            if not data or any(va < e and st < va + len(data) for st, e in forbidden()): raise SystemExit(f'patch record in a forbidden range: {va:#x}')
            body += struct.pack('<2I', va, len(data)) + data + bytes(-len(data) % 4)
        head = struct.pack('<4s5I', b'ZHTP', 1, len(V['vmap_rows']), len(recs), len(body), sum(struct.unpack(f'<{len(body) // 4}I', body)) & 0xFFFFFFFF)
        return s, t, recs, head + bytes(32 - len(head)) + body

    codebooks = {'sc': a.codebook, 'tc': a.tc_codebook}
    options = options_address(exe_sc, *(V['exe'] for V in VS))
    code0, syms0 = assemble_hook(a.work, [(0, 1)] * len(VS), codebooks, options)
    patches = []
    for V in VS:
        _, _, V['recs'], V['pf'] = build_patch(code0, syms0, V)
        V['patch_sectors'] = -(-len(V['pf']) // 2048)
        if V['patch_sectors'] * 2048 > SCRATCH_MAX: raise SystemExit(f"{V['tag']}: patch file exceeds the scratch buffer")
        V['patch_lba'] = place(('patch file' if V['tag'] == 'tc' else 'HK patch file'), V['pf'])
        patches.append((V['patch_lba'], V['patch_sectors']))
    code, syms = assemble_hook(a.work, patches, codebooks, options)
    menu = None
    if getattr(a, 'builtin_cheats', False):
        from build_builtin_cheats import MENU_BASE, menu_sites, compile_menu, install_menu
        menu, menu_symbols = compile_menu(a.work / 'builtin-cheats', syms, ED)
    for V in VS:
        SC, TC, recs2, pf2 = build_patch(code, syms, V)
        if recs2 != V['recs'] or pf2 != V['pf']: raise SystemExit(f"{V['tag']}: patch depends on the hook bytes")
        if menu is not None:
            install_menu(SC, menu, menu_symbols, ED.key)
            install_menu(TC, menu, menu_symbols, ED.key)
            SC, TC = Elf(SC.b), Elf(TC.b)
        replay = Elf(bytes(SC.b)); pf = V['pf']; body = pf[32:]; nv, nr = struct.unpack_from('<2I', pf, 8); q = nv * 12
        for _ in range(nr):
            va, n = struct.unpack_from('<2I', body, q); q += 8; replay.put(va, body[q:q + n]); q += n + (-n % 4)
        if replay.b != TC.b: raise SystemExit(f"{V['tag']}: patch replay differs from its executable")
        V['exe_out'] = TC
    if cur > dmy.extent_lba + dmy.size // 2048: raise SystemExit('DMY is full')

    # ---- write and read back ----------------------------------------------------------------------------
    from special_disc.resource_view import ResourceView
    if isinstance(a.sc, ResourceView):
        a.sc.materialize(staged)
    else:
        subprocess.run(['cp', '-c', str(a.sc), str(staged)], check=True)
    exe_e = sc.m[EXE]; spans = []
    with open(staged, 'r+b') as f:
        f.seek(dmy.extent_lba * 2048)
        if any(f.read((cur - dmy.extent_lba) * 2048)): raise SystemExit('DMY area not empty')
        for name, lba, data in items:
            n = -(-len(data) // 2048) * 2048
            f.seek(lba * 2048); f.write(data + bytes(n - len(data))); spans.append((lba * 2048, lba * 2048 + n))
        if len(SC.b) == exe_e.size:
            f.seek(exe_e.extent_lba * 2048); f.write(SC.b); spans.append((exe_e.extent_lba * 2048, exe_e.extent_lba * 2048 + len(SC.b)))
    with open(staged, 'r+b') as f:
        for name, lba, data in tail_items:
            if f.seek(0, 2) != lba * 2048: raise SystemExit(f'image end moved before {name}')
            f.write(data)
            f.write(bytes(-len(data) % 2048))
            f.seek(lba * 2048)
            if f.read(len(data)) != data: raise SystemExit(f'readback appended {name}')
    relocation = None
    tail_volume = None
    if tail_items and (len(SC.b) == exe_e.size or menu is not None and ED.key != 'sp'):
        from special_disc.event_gallery.udf import relocate
        first_tail_lba = tail_items[0][1]
        tail_volume = relocate(staged, {}, appended_start=first_tail_lba)
        if not tail_volume['partition_extended'] or staged.stat().st_size > 4_700_000_000:
            raise SystemExit('regional resource tail exceeds the single-layer disc budget')
        spans.extend((lba * 2048, (lba + 1) * 2048) for lba in tail_volume['metadata_blocks_written']
                     if lba < first_tail_lba)
        with staged.open('rb') as f:
            for lba in range(16, 32):
                f.seek(lba * 2048)
                block = f.read(2048)
                if block[1:6] == b'CD001' and block[0] in (1, 2):
                    volume_size = tail_volume['image_blocks']
                    if block[80:88] != struct.pack('<I', volume_size) + struct.pack('>I', volume_size):
                        raise SystemExit('ISO9660 volume size does not cover the language resource tail')
                    spans.append((lba * 2048 + 80, lba * 2048 + 88))
    if len(SC.b) != exe_e.size:
        from special_disc.iso_relocation import append_members, verify_relocation
        relocation = append_members(staged, sc.m, {EXE: bytes(SC.b)}, allowed_udf={EXE, 'EFF/VEFF2DX.BIN'} if menu is not None and ED.key != 'sp' else None, catalog_policy='inherit')
        verify_relocation(staged, sc.m, {EXE: bytes(SC.b)}, relocation)
        base_size = a.sc.stat().st_size
        spans.extend((start, min(end, base_size)) for start, end in relocation['touched_spans'] if start < base_size)
        if tail_volume is not None:
            tail_volume = relocation['udf']
    # The executable's span is excluded from the comparison below, so read it back the way the console finds it:
    # through the staged image's own directory. The receipt records the hash of these bytes.
    staged_exe = Disc(staged).read(EXE)
    if staged_exe != bytes(SC.b): raise SystemExit(f'readback {EXE}: the staged image does not hold the assembled executable')
    with open(staged, 'rb') as f:
        def at(off, n): f.seek(off); return f.read(n)
        for V in VS:
            if at(V['patch_lba'] * 2048, len(V['pf'])) != V['pf']:
                raise SystemExit(f"readback {V['tag']} ZHTP patch")
            for off, lba, n in V['vmap_rows']:
                if lba == V['vt1_tail_lba']: continue                   # the appended VT1 copy (read back when written)
                name = next(k for k, v in V['report']['copied_members'].items() if v['tc_lba'] == lba)
                if at(lba * 2048, len(V['copied'][name])) != V['copied'][name]: raise SystemExit(f"readback {V['tag']} {name}")
            if V['font'] is not None and at(vt1m.extent_lba * 2048 + V['font_offset'], len(V['font'])) != V['font']:
                raise SystemExit(f"readback {V['tag']} font")
            if V['menu_chunk'] is not None and at(vt1m.extent_lba * 2048 + V['menu_chunk'][0], V['menu_chunk'][1]) != V['menu_bytes']:
                raise SystemExit(f"readback {V['tag']} title menu")
            if V['title_shift'] is not None:
                table, count, group = (SP_TITLE_TABLE, 28, SP_TITLE_GROUP) if ED.key == 'sp' else (ED.main['title_table'], TITLE_COUNT, TITLE_GROUP)
                inner = struct.unpack('<%dI' % count, V['exe_out'].get(table, count * 4))
                base = vt1m.extent_lba * 2048 + V['o_sc'][group]
                o_tc = V['o_tc']
                if at(base + inner[0], inner[-1] - inner[0]) != V['v_tc'][o_tc[group]:o_tc[group + 1]]:
                    raise SystemExit(f"readback {V['tag']} titles")
    merged = []
    for st, e in sorted(spans):
        if merged and st <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], e)
        else: merged.append([st, e])
    spans = [tuple(x) for x in merged]; pos = 0
    with a.sc.open('rb') as x, open(staged, 'rb') as y:
        size = x.seek(0, 2)
        if size != y.seek(0, 2) and relocation is None and not tail_items: raise SystemExit('image size changed')
        for st, e in spans + [(size, size)]:
            x.seek(pos); y.seek(pos); n = st - pos
            while n > 0:
                k = min(n, 64 << 20)
                if x.read(k) != y.read(k): raise SystemExit('bytes outside the written spans changed')
                n -= k
            pos = e
    def patch_report(V):
        return {'lba': V['patch_lba'], 'sectors': V['patch_sectors'], 'bytes': len(V['pf']), 'vmap_rows': len(V['vmap_rows']),
                'records': len(V['recs']), 'record_bytes': sum(len(d) for _, d in V['recs'])}
    tw = VS[0]
    receipt = {'sc_iso': str(a.sc), 'tc_iso': str(a.tc), 'iso': str(a.out), 'output': disc_identity(staged),
               'inputs': {region: disc_identity(path) for region, path in
                          [('sc', a.sc), ('tw', a.tc), ('hk', a.hk)] if path}, 'languages': langs,
               'hook_bytes': len(code), 'dmy': [{'item': n, 'lba': l, 'bytes': len(d)} for n, l, d in items],
               'dmy_used_bytes': (cur - dmy.extent_lba) * 2048, 'dmy_bytes': dmy.size,
               'tail': [{'item': n, 'lba': l, 'bytes': len(d)} for n, l, d in tail_items],
               'patch': patch_report(tw), 'sc_exe_sha256': sha(staged_exe), 'tc_exe_sha256': sha(tw['exe_out'].b), 'edition': ED.key,
               'executable_relocation': relocation and {k: relocation[k] for k in ('changes', 'old_size', 'new_size')},
               **tw['report']}
    if menu is not None:
        receipt['builtin_cheats'] = {'address': MENU_BASE[ED.key], 'size': len(menu), 'sha256': sha(menu),
                                   'hooks': {hex(site): SC.get(site, 4 * (len(spec) - 1)).hex()
                                             for site, spec in menu_sites(ED.key).items()}}
        if ED.key == 'sp':
            receipt['builtin_cheats']['language_imports'] = [syms[key] for key in ('lang','set_msg','restore_msg')]
    if tail_volume is not None:
        receipt['tail_volume'] = {k: tail_volume[k] for k in ('image_blocks', 'partition_length', 'anchors_written')}
    if a.hk:
        hk = VS[1]
        receipt['hk'] = {'hk_iso': str(a.hk), 'patch': patch_report(hk), 'hk_exe_sha256': sha(hk['exe_out'].b), **hk['report']}
    staged_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({k: receipt[k] for k in ('hook_bytes', 'patch', 'dmy_used_bytes', 'copied_members', 'vt1')}, ensure_ascii=False, indent=1))
    if a.hk:
        print(json.dumps({'hk_patch': receipt['hk']['patch'], 'hk_copied': list(receipt['hk']['copied_members'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
