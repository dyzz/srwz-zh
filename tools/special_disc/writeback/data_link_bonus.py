"""Default Z male/female clear bonuses; Data Link becomes an information page.

Only the two Z flags are normalized. The five native SP clear queries, reward
tables, and opt-in reward application remain intact. No Z memory-card read is
entered from the Data Link menu. See DATA_LINK_REWARD_MECHANISM_20260920.md.
"""
from __future__ import annotations

import hashlib
import struct

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import decode_text, encode_text
from special_disc.writeback.install_font import sp_offsets, VT1_TABLE

DELTA = 0xFF680
EXE_SIZE = 3982200
FLAG_VA = 0x319DD0
FLAG_BEFORE = bytes.fromhex(
    'c0ffbd274900033c3000bfff4900013c2000b27f1000b17f0000b07fa08d20a0'
    '6100013c062a22900f0042300100423003004010a08d632401000224000062a0'
    '010060a06100013c062a22900f004230020042300200401001000224010062a0')
# Keep the original stack frame and saved registers, OR both Z flags into
# both SP state copies, then produce flags[0:2] = [1, 1]. Fall through into
# the untouched SP clear-query loop at 0x319E30.
FLAG_AFTER = struct.pack('<24I',
    0x27BDFFC0, 0xFFBF0030, 0x7FB20020, 0x7FB10010, 0x7FB00000,
    0x3C010061, 0x90222A06, 0x34420003, 0xA0222A06,
    0x3C01005E, 0x9022C546, 0x34420003, 0xA022C546,
    0x3C030049, 0x24638DA0, 0x24020001, 0xA0620000, 0xA0620001,
    0, 0, 0, 0, 0, 0)
MENU_VA = 0x31B810
MENU_BEFORE = bytes.fromhex('6002110c')  # jal 0x440980, Z reader initializer
MENU_AFTER = bytes.fromhex('13000010')   # b 0x31B860, return to story menu
CONTEXTS = (
    (0x319DD0, 0x319EA0, 'ed49cd8e807e1557462a126c1addc2cbb8a54a77d76824be2a9463780bb6cfc9'),
    (0x31B7B0, 0x31B870, 'ab3ea3df14d844086b1bf5d3bb91d43773ad4ebcd6ef8354103372d6f88f664b'),
)
# The native preview infers eligibility from two padding bytes in a copied
# label. Translated, shorter NUL-terminated labels do not carry that padding.
# Read the same seven flags as the grant loop, retaining native label clipping.
DISPLAY_VA = 0x4378C0
DISPLAY_BEFORE = bytes.fromhex(
    '2801a22700004390810002240a0062142d8000002901a2270000439040000224'
    '050062141e01a2270100102404000010000040a0000000002801a227000040a0')
DISPLAY_AFTER = struct.pack('<16I',
    0x3C020049, 0x24428DA0, 0x00561021, 0x90500000,
    0x12000009, 0x27A2011E, 0x10000009, 0xA0400000,
    0, 0, 0, 0, 0, 0, 0x27A20128, 0xA0400000)
SITES = ((FLAG_VA, FLAG_BEFORE, FLAG_AFTER), (MENU_VA, MENU_BEFORE, MENU_AFTER),
         (DISPLAY_VA, DISPLAY_BEFORE, DISPLAY_AFTER))
POLICY = 'default_both_z_routes_without_z_save_io'
# Product behavior override, separate from the faithful original-text corpus.
# Exactly one existing VT1 page, nine rows of 28 two-byte cells plus LF.
PAGE_LINES = (
    '　数据链接',
    '　本作已默认启用《超级机器人大战Z》',
    '男、女主角路线的通关奖励。',
    '　无需读取本篇存档。开始各组剧情时，',
    '可选择领取资金、BS、PP和强化零件奖励。',
    '　两条路线的奖励可以同时获得。',
    '　特别篇自身的通关奖励仍按实际进度获得。',
    '',
    '　　　返回剧情选择吗？',
)
PAGE_TEXT = '\n'.join(PAGE_LINES)
PAGE_SIZE = 9 * 57
HINTS = (
    (0x3C46C0, 0x50, '　已默认启用《超级机器人大战Z》双路线通关奖励。'),
    (0x3C4710, 0x40, '无需读取本篇存档，开始各组剧情时可选择领取。'),
    (0x3C4750, 0x2E, '查看奖励说明。'),
)
TEXT_OVERRIDES = {'sd/vt1/40/0': PAGE_TEXT,
                  **{f'sd/exe/{at:X}': text for at, _, text in HINTS}}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def patch_executable(exe: bytes) -> bytes:
    require(len(exe) == EXE_SIZE, 'SP Data Link executable size drift')
    normalized = bytearray(exe)
    for va, before, after in SITES:
        at = va - DELTA
        require(exe[at:at+len(before)] in (before, after), f'SP Data Link preimage drift at {va:#x}')
        normalized[at:at+len(before)] = before
    for start, end, digest in CONTEXTS:
        require(hashlib.sha256(normalized[start-DELTA:end-DELTA]).hexdigest() == digest,
                f'SP Data Link instruction context drift at {start:#x}')
    result = bytearray(exe)
    for va, _, after in SITES:
        at = va - DELTA
        result[at:at+len(after)] = after
    return bytes(result)


def encode_page(table, overrides):
    lines = []
    for text in PAGE_LINES:
        data = encode_text(text.replace(' ', '　'), table, overrides=overrides, terminate=False)
        require(len(data) % 2 == 0 and len(data) <= 56, 'SP default bonus page exceeds fixed grid')
        lines.append(data + bytes.fromhex('8140') * ((56-len(data))//2) + b'\n')
    return b''.join(lines)


def verify_data_link_bonus(exe, vt1, readback):
    require(patch_executable(exe) == exe, 'SP default Z bonus code is missing')
    for at, size, text in HINTS:
        actual = decode_text(exe, at, readback, end=at+size)
        require(actual.text == text and actual.terminator == 'nul', 'SP default bonus menu hint mismatch')
    offsets = sp_offsets(exe, VT1_TABLE, len(vt1))
    data = decode_production(vt1[offsets[40]:offsets[41]]).output
    require(len(data) >= PAGE_SIZE and all(data[i*57+56] == 10 for i in range(9)),
            'SP default bonus page grid drift')
    lines = [decode_text(data[i*57:i*57+56]+b'\0', 0, readback).text.rstrip('　') for i in range(9)]
    require(lines == list(PAGE_LINES), 'SP default bonus explanation readback mismatch')
    return dict(policy=POLICY, z_routes=['male', 'female'], z_save_io=False,
                sp_clear_checks='unchanged', rewards='native_table_and_opt_in_unchanged',
                explanation='sd/vt1/40/0', explanation_text=PAGE_TEXT,
                menu_hints={f'sd/exe/{at:X}': text for at, _, text in HINTS})


def apply_data_link_bonus(exe, vt1, table, overrides, readback):
    result = bytearray(patch_executable(exe))
    for at, size, text in HINTS:
        require(b'\0' in exe[at:at+size], 'SP menu hint source terminator missing')
        payload = encode_text(text, table, overrides=overrides, terminate=True)
        require(len(payload) <= size, 'SP menu hint exceeds its original text slot')
        result[at:at+size] = payload + bytes(size-len(payload))
    result = bytes(result)
    offsets = sp_offsets(exe, VT1_TABLE, len(vt1)); a, z = offsets[40:42]
    stored = vt1[a:z]; original = decode_production(stored)
    require(len(original.output) >= PAGE_SIZE and len(original.output) % 57 == 0,
            'SP Data Link source page shape drift')
    page = encode_page(table, overrides)
    decoded = page + original.output[PAGE_SIZE:]
    if decoded == original.output:
        output = vt1
    else:
        packed = reencode_changed_suffix(stored, decoded, strategy='rust-fit',
                                         max_output_size=z-a, original_result=original)
        require(len(packed) <= z-a and decode_production(packed).output == decoded,
                'SP default bonus page repack/readback failed')
        output = vt1[:a] + packed + bytes(z-a-len(packed)) + vt1[z:]
    report = verify_data_link_bonus(result, output, readback)
    report.update(executable_changed_bytes=sum(x != y for x, y in zip(exe, result)),
                  sites=[dict(virtual_address=hex(va), file_offset=hex(va-DELTA),
                              before_hex=before.hex(), after_hex=after.hex()) for va, before, after in SITES],
                  vt1_chunk=40, vt1_range=[a, z], decoded_other_pages_unchanged=True,
                  runtime='pending')
    return result, output, report
