"""Per-edition engine addresses for the dual-language hook (lang_hook.S) and its assembler (assemble_dual.py).

ORIGINAL holds the addresses the Original dual disc was built and verified with. SP's were found by a masked
instruction search of SLPS_259.20 against SLPS_258.87 and by following the matched code's own references
(docs/ZH_HANT_SP_DUAL_PLAN_20261117.md §2).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Edition:
    key: str
    exe: str
    cave: tuple                  # (start, end): hook code and data
    boot_site: tuple             # (va, stock word): `jal BOOT_CALL` the hook replaces
    title_site: tuple            # (va, stock word): the title call the panel wraps
    save_dir: str                # memory-card directory for LANG.BIN (with icon.sys / icon when created)
    icon_title: str              # card-browser title (Shift-JIS, line 2 from byte 22)
    hook: dict = field(default_factory=dict)   # .equ values for lang_hook.S (edition.inc)
    forbidden: tuple = ()        # ranges no patch record may touch besides the cave and the hook sites
    runtime_buf: int = 0         # 0: the hook's card / panel buffer lives in the cave; else its runtime-only address
    # Main-game engine (Original, BEST): VT1 is read chunk by chunk through one offset table, so the Traditional font,
    # title menu and stage titles are reached by rewriting their own loaders (assemble_dual.py). Empty for SP.
    #   font_buffer   word holding the font buffer size
    #   vt1_table     the executable's VT1 offset table (15 words)
    #   title_table   inner table of the stage-title group (117 words)
    #   font_loader   [(va, stock word)] x7: length lui/ori, offset lui/ori, the subtraction, the glyph fallback pair
    #   menu_loader   [(va, stock word)] x6: the title screen's read of VT1 chunk 6
    main: dict = field(default_factory=dict)


ORIGINAL = Edition(
    key='original', exe='SLPS_258.87',
    cave=(0x78B640, 0x78C4C0),                 # free tail of the Latin-bank segment (payload ends 0x78b610)
    # 84-byte card / panel buffer in the gap between the overlays' end (0x789D00) and the Latin-bank segment
    # (0x789E00): no segment loads there and a full route showed only the loader's zero fill (2026-11-18,
    # work/analysis/zh-hk-tw-20261118/gw1). 0x78C4C0-0x78C6C0 after the cave is the Latin payload's work area.
    runtime_buf=0x789D00,
    boot_site=(0x141010, 0x0C0400BC), title_site=(0x155CF8, 0x0C0553EC),
    save_dir='/BISLPS-25887L', icon_title='スーパーロボット大戦Ｚ言語設定',
    hook=dict(
        BOOT_CALL=0x1002F0, PAD_BUF=0x59C100, PAD_PRESSED=0x59C24E, PAD_REPEAT=0x59C252, VMAP_PTR=0x46DF08,
        MC_GETINFO=0x132470, MC_OPEN=0x131D10, MC_READ=0x1320C0, MC_CLOSE=0x131E70, MC_SYNC=0x132350,
        MC_MKDIR=0x131E38, MC_WRITE=0x1321D8,
        CD_PREP=0x12F698, CD_READ=0x12F8B8, CD_SYNC=0x12EE80, CD_ERROR=0x12FA98, CD_MODE=0x46DF10,
        TITLE_CALL=0x154FB0, TITLE_MODE_WORD=0, TITLE_READY=0, TITLE_SUBSTATE=-0x7A2C, TITLE_IDLE=3,
        MB_CREATE=0x36BBE0, MB_SELECT=0x36BC20, MB_INPUT=0x36BC30, MB_DRAW=0x36BCC0, MB_DESTROY=0x36BD50,
        TEXT_PASS=0x13AC90, KVP_DRAW=0x36B330, MSG_TEXT=0x4171F0, MSG_ATTR=0x42BF90,
        ICON_SYS=0x414080, SAVE_ICON=0x414450, SAVE_ICON_SIZE=11664,
        BOX_X=-0x2F, BOX_Y=-0x2E,
        ICON_OK=47, ICON_CANCEL=39,             # KVP styles: small lit ○ / × button (45/37 large, +1 dimmed)
        ICON_Y=-12,                             # hint row of the panel box (style y: screen ≈ 2y + 226 in 448 lines)
        ICON_OK_X=-63, ICON_CANCEL_X=17,        # symbol centre ≈ x + 334; over the hint's blanks before 保存 / 取消
    ),
    forbidden=((0x3F7D68, 0x3F7D6C), (0x798000, 0x7A0000), (0x789D00, 0x789E00),
               *((a, a + 8) for a in (0x189580, 0x189B70, 0x189600, 0x18AC10)),          # music hooks
               *((a, a + 4) for a in (0x1001D0, 0x1001D8, 0x140644, 0x140650, 0x3F3FB4))),  # heap words
    main=dict(
        font_buffer=0x3F7D68, vt1_table=0x3F8680, title_table=0x41A2B0,
        font_loader=[(0x13A174, 0x84238664), (0x13A184, 0x84228666), (0x13A19C, 0x8C650000), (0x13A1A0, 0x8C420000),
                     (0x13A1A8, 0x00453023), (0x13A95C, 0x1000000C), (0x13A960, 0xA4200062)],
        # lh v0,-0x7998(at); sll; addu a1; addu v0; lw a1; lw v0
        menu_loader=[(0x154C8C, 0x84228668), (0x154C90, 0x00021080), (0x154C98, 0x00A22821), (0x154CA0, 0x00621021),
                     (0x154CA4, 0x8CA50000), (0x154CA8, 0x8C420000)],
    ),
)

# BEST is the same engine as Original with small shifts (2026-11-19): every address below is the Original one found
# again in the built BEST executable by a unique masked-instruction match of the surrounding code, and for data by
# the operands of that matched code. Code moves by 0 / +0x3A0 / +0x600, initialised data by +0x780 (the message
# attribute table by +0x830), runtime memory by +0x800. BEST saves into the Original's card directory, so the
# language setting file is shared between the two discs.
BEST = Edition(
    key='best', exe='SLPS_732.70',
    cave=(0x78BE40, 0x78CCC0),                 # free tail of the Latin-bank segment (0x78A600; payload ends 0x78BE10)
    runtime_buf=0x78A500,                      # the gap below the Latin-bank segment, as on Original
    boot_site=(0x141010, 0x0C0400BC), title_site=(0x156098, 0x0C0554D4),
    save_dir='/BISLPS-25887L', icon_title='スーパーロボット大戦Ｚ言語設定',
    hook=dict(
        BOOT_CALL=0x1002F0, PAD_BUF=0x59C900, PAD_PRESSED=0x59CA4E, PAD_REPEAT=0x59CA52, VMAP_PTR=0x46E708,
        MC_GETINFO=0x132470, MC_OPEN=0x131D10, MC_READ=0x1320C0, MC_CLOSE=0x131E70, MC_SYNC=0x132350,
        MC_MKDIR=0x131E38, MC_WRITE=0x1321D8,
        CD_PREP=0x12F698, CD_READ=0x12F8B8, CD_SYNC=0x12EE80, CD_ERROR=0x12FA98, CD_MODE=0x46E710,
        TITLE_CALL=0x155350, TITLE_MODE_WORD=0, TITLE_READY=0, TITLE_SUBSTATE=-0x7A2C, TITLE_IDLE=3,
        MB_CREATE=0x36C1E0, MB_SELECT=0x36C220, MB_INPUT=0x36C230, MB_DRAW=0x36C2C0, MB_DESTROY=0x36C350,
        TEXT_PASS=0x13AC90, KVP_DRAW=0x36B930, MSG_TEXT=0x417970, MSG_ATTR=0x42C7C0,
        ICON_SYS=0x414800, SAVE_ICON=0x414BD0, SAVE_ICON_SIZE=11664,
        BOX_X=-0x2F, BOX_Y=-0x2E,
        ICON_OK=47, ICON_CANCEL=39,
        ICON_Y=-12, ICON_OK_X=-63, ICON_CANCEL_X=17,
    ),
    forbidden=((0x3F84E8, 0x3F84EC), (0x798000, 0x7A0000), (0x78A500, 0x78A600),
               *((a, a + 8) for a in (0x189920, 0x189F10, 0x1899A0, 0x18AFB0)),          # music hooks
               *((a, a + 4) for a in (0x1001D0, 0x1001D8, 0x140644, 0x140650, 0x3F4734))),  # heap words
    main=dict(
        font_buffer=0x3F84E8, vt1_table=0x3F8E00, title_table=0x41AA30,
        font_loader=[(0x13A174, 0x84238DE4), (0x13A184, 0x84228DE6), (0x13A19C, 0x8C650000), (0x13A1A0, 0x8C420000),
                     (0x13A1A8, 0x00453023), (0x13A95C, 0x1000000C), (0x13A960, 0xA4200062)],
        menu_loader=[(0x15502C, 0x84228DE8), (0x155030, 0x00021080), (0x155038, 0x00A22821), (0x155040, 0x00621021),
                     (0x155044, 0x8CA50000), (0x155048, 0x8C420000)],
    ),
)

SP = Edition(
    key='sp', exe='SLPS_259.20',
    cave=(0x81C600, 0x81E000),                 # above the stock image end, below the gallery's moved heap (0x8C0000)
    boot_site=(0x141B28, 0x0C0400BC),
    title_site=(0x14214C, 0x0C0559D0),         # main loop -> mode dispatcher 0x156740 (title = modes 90-111)
    save_dir='/BISLPS-25920L', icon_title='スーパーロボット大戦Ｚスペシャルディスク言語設定',
    hook=dict(
        BOOT_CALL=0x1002F0, PAD_BUF=0x625000, PAD_PRESSED=0x62514E, PAD_REPEAT=0x625152, VMAP_PTR=0x4ED188,
        MC_GETINFO=0x132C08, MC_OPEN=0x1324A8, MC_READ=0x132858, MC_CLOSE=0x132608, MC_SYNC=0x132AE8,
        MC_MKDIR=0x1325D0, MC_WRITE=0x132970,
        CD_PREP=0x12FE30, CD_READ=0x130050, CD_SYNC=0x12F618, CD_ERROR=0x130230, CD_MODE=0x4ED190,
        TITLE_CALL=0x156740, TITLE_MODE_WORD=0x6163C8, TITLE_READY=0x6163D8, TITLE_SUBSTATE=0, TITLE_IDLE=100,
        MB_CREATE=0x3914C0, MB_SELECT=0x391500, MB_INPUT=0x391510, MB_DRAW=0x3915D0, MB_DESTROY=0x391660,
        TEXT_PASS=0x13B730, KVP_DRAW=0x390BE0, MSG_TEXT=0x4728F0, MSG_ATTR=0x49A7F0,
        ICON_SYS=0x46F210, SAVE_ICON=0x46F5E0, SAVE_ICON_SIZE=13038,
        BOX_X=-0x2F, BOX_Y=-0x2E,
        ICON_OK=45, ICON_CANCEL=37,             # SP's style table is offset by -2 from Original's
        ICON_Y=-12, ICON_OK_X=-63, ICON_CANCEL_X=17,
    ),
    forbidden=(                                    # SP payload text (no-BGM labels, gallery names) may differ
               *((a, a + 8) for a in (0x18B1F0, 0x18B7E0, 0x18B270, 0x18C8A0)),         # music hooks
               *((a, a + 4) for a in (0x1001D0, 0x1001D8, 0x1410F4, 0x141100, 0x44E734))),  # heap words
)

EDITIONS = {e.key: e for e in (ORIGINAL, BEST, SP)}


def edition_inc(e: Edition) -> str:
    return ''.join(f'        .equ    {k}, {v:#x}\n' if v >= 0 else f'        .equ    {k}, -{-v:#x}\n'
                   for k, v in e.hook.items())


def paths_inc(e: Edition) -> str:
    d = e.save_dir
    return (f'lang_path:\n        .asciz  "{d}/LANG.BIN"\nlang_dir:\n        .asciz  "{d}"\n'
            f'icon_sys_path:\n        .asciz  "{d}/icon.sys"\nicon_path:\n        .asciz  "{d}/a20.ico"\n')
