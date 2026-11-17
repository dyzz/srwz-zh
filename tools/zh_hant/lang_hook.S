# M1 boot language hook. Replaces `jal 0x1002f0` at 0x141010 (pad ports open at 0x141008; no text member
# lookup and no font load yet, those start at 0x141018 / 0x1410d8).
#
# Traditional: read the patch file from DMY into a fixed scratch buffer, check magic and checksum, rewrite the
# loaded VMAP rows, copy every executable record, wipe the scratch buffer, flush both caches. Nothing is
# allocated: the heap is untouched in both modes, and the scratch buffer (all zero at this point) is
# zero again afterwards. Any check failure leaves the game in Simplified.
#
# Settings source: /BISLPS-25887L/LANG.BIN on the memory card in port 0 (16 bytes: 'ZHLG', version, value,
# ~value). Version 1: value = lang. Version 2: value = lang | plain zero << 8 | Japanese quotes << 16.
# lang 1 = Traditional. No card, no file or any mismatch = Simplified with the default look. Debug override:
# SELECT held on port 0 at boot forces Traditional without touching the card. The two display flags go to the
# proportional hooks' options word (OPTIONS, srwz.proportional_hooks) in both languages.
#
# Patch file (little endian): 32-byte header
#   +0 'ZHTP'  +4 version  +8 vmap row count  +12 record count  +16 body bytes  +20 u32 sum of body words
# body: vmap rows (row offset, lba, sectors), then records (address, length, bytes padded to 4).
        .set noreorder
        .set noat
        .include "params.inc"           # PATCH_LBA, PATCH_SECTORS, SCRATCH, OPTIONS
        .equ    ICON_OK, 47             # KVP styles: small lit ○ / × button (45/37 large, +1 dimmed)
        .equ    ICON_CANCEL, 39
        .equ    ICON_Y, -12             # hint row of the panel box (style y: screen ≈ 2y + 226 in 448 lines)
        .equ    ICON_OK_X, -63          # style x: symbol centre ≈ x + 334; over the hint's blanks before 保存 / 取消
        .equ    ICON_CANCEL_X, 17       # ("　　保存　　　取消", 16 px a code, centred on x ≈ 322), 3 px left of the cell centre
        .text
        .globl lang_hook
lang_hook:
        addiu   $sp, $sp, -64
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        sd      $s2, 24($sp)
        sd      $s3, 32($sp)
        jal     0x1002f0                # the call this hook replaced
        nop
# ---- language source: SELECT on port 0 ------------------------------------------------------------------
        lui     $s0, 0x2059             # pad port 0 buffer 0x59c100 through the uncached mirror
        ori     $s0, $s0, 0xc100
        mfc0    $s1, $9                 # Count: timeout start
        addiu   $s3, $zero, 1           # SELECT not held (active low)
        lui     $t9, 0x0aba             # ~0.6 s at 294.912 MHz
poll:   lbu     $t0, 0($s0)
        lbu     $t1, 1($s0)
        bnez    $t0, other
        nop
        bnez    $t1, got
        move    $t3, $s0
other:  lbu     $t0, 0x80($s0)
        lbu     $t1, 0x81($s0)
        bnez    $t0, wait
        nop
        bnez    $t1, got
        addiu   $t3, $s0, 0x80
wait:   mfc0    $t2, $9
        subu    $t2, $t2, $s1
        sltu    $t2, $t2, $t9
        bnez    $t2, poll
        nop
        b       card
        nop
got:    lbu     $t0, 2($t3)             # buttons, active low; bit 0 = SELECT
        andi    $s3, $t0, 1
card:   jal     read_setting            # language and display flags (always: the flags apply in both)
        nop
        beqz    $s3, tc                 # SELECT held: debug override
        nop
        beqz    $v0, done
        nop
tc:
# ---- read the patch file -------------------------------------------------------------------------------
        addiu   $v1, $zero, 0x64        # FlushCache(0): no dirty line may shadow the DMA target
        move    $a0, $zero
        syscall
        li      $a0, PATCH_LBA
        li      $a1, PATCH_SECTORS
        li      $a2, SCRATCH
        jal     read_sectors
        nop
        li      $s0, SCRATCH | 0x20000000       # read it back uncached
        lw      $t0, 0($s0)
        li      $t1, 0x5054485a                 # 'ZHTP'
        bne     $t0, $t1, wipe
        lw      $t0, 4($s0)
        addiu   $t1, $zero, 1
        bne     $t0, $t1, wipe
        lw      $t1, 16($s0)                    # body bytes
        li      $t2, PATCH_SECTORS * 2048 - 32
        sltu    $t2, $t2, $t1
        bnez    $t2, wipe
        addiu   $t3, $s0, 32
        addu    $t4, $t3, $t1                   # body end
        move    $t5, $zero
1:      beq     $t3, $t4, 2f
        nop
        lw      $t6, 0($t3)
        addu    $t5, $t5, $t6
        b       1b
        addiu   $t3, $t3, 4
2:      lw      $t6, 20($s0)
        bne     $t5, $t6, wipe
        nop
# ---- VMAP rows: point the loaded table at the DMY copies ------------------------------------------------
        lw      $s2, 8($s0)
        addiu   $s1, $s0, 32
        lui     $t9, 0x47
        lw      $t9, -0x20f8($t9)               # 0x46df08: loaded VMAP
3:      beqz    $s2, 4f
        lw      $t2, 0($s1)
        lw      $t4, 4($s1)
        lw      $t5, 8($s1)
        addu    $t2, $t2, $t9
        sw      $t4, 40($t2)
        sw      $t5, 44($t2)
        addiu   $s1, $s1, 12
        b       3b
        addiu   $s2, $s2, -1
# ---- executable records ---------------------------------------------------------------------------------
4:      lw      $s2, 12($s0)
5:      beqz    $s2, 7f
        lw      $t2, 0($s1)                     # address
        lw      $t4, 4($s1)                     # length
        addiu   $s1, $s1, 8
        move    $t5, $zero
6:      addu    $t6, $s1, $t5
        lbu     $t7, 0($t6)
        addu    $t6, $t2, $t5
        sb      $t7, 0($t6)
        addiu   $t5, $t5, 1
        bne     $t5, $t4, 6b
        nop
        addiu   $t4, $t4, 3
        srl     $t4, $t4, 2
        sll     $t4, $t4, 2
        addu    $s1, $s1, $t4
        b       5b
        addiu   $s2, $s2, -1
7:      lui     $t0, %hi(lang)
        addiu   $t1, $zero, 1
        sw      $t1, %lo(lang)($t0)
# ---- wipe the scratch buffer (it was all zero before the read) and flush ---------------------------------
wipe:   li      $t0, SCRATCH | 0x20000000
        li      $t1, (SCRATCH | 0x20000000) + PATCH_SECTORS * 2048
8:      sd      $zero, 0($t0)
        sd      $zero, 8($t0)
        addiu   $t0, $t0, 16
        bne     $t0, $t1, 8b
        nop
        addiu   $v1, $zero, 0x64        # FlushCache(0): write back data cache
        move    $a0, $zero
        syscall
        addiu   $v1, $zero, 0x64        # FlushCache(2): invalidate instruction cache
        addiu   $a0, $zero, 2
        syscall
done:   lui     $t0, %hi(disp)          # display flags -> the proportional hooks (after any patch record)
        lw      $t1, %lo(disp)($t0)
        lui     $t0, %hi(OPTIONS)
        sw      $t1, %lo(OPTIONS)($t0)
        ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        ld      $s2, 24($sp)
        ld      $s3, 32($sp)
        jr      $ra
        addiu   $sp, $sp, 64

# read_setting() -> 1 when the card holds a valid Traditional setting. libmc is initialised at 0x141000.
read_setting:
        addiu   $sp, $sp, -48
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sw      $zero, 16($sp)                  # bytes read
        move    $a0, $zero                      # sceMcGetInfo(0, 0, &type, &free, &format): mcserv refuses
        move    $a1, $zero                      # file calls on a card nobody has queried yet (-13)
        addiu   $a2, $sp, 24
        addiu   $a3, $sp, 28
        jal     0x132470
        addiu   $t0, $sp, 32
        bnez    $v0, rs_no
        nop
        jal     mc_wait
        nop
        sw      $v0, 36($sp)                    # 0 same card, -1 new formatted card; others: no usable card
        addiu   $t0, $zero, -1
        slt     $t1, $v0, $t0
        bnez    $t1, rs_no
        slt     $t1, $zero, $v0
        bnez    $t1, rs_no
        nop
        move    $a0, $zero                      # port 0
        move    $a1, $zero                      # slot 0
        lui     $a2, %hi(lang_path)
        addiu   $a2, $a2, %lo(lang_path)
        jal     0x131d10                        # sceMcOpen(port, slot, name, O_RDONLY)
        addiu   $a3, $zero, 1
        bnez    $v0, rs_no
        nop
        jal     mc_wait
        nop
        bltz    $v0, rs_no                      # no card / no file
        move    $s0, $v0                        # fd
        move    $a0, $s0
        lui     $a1, %hi(setting)
        addiu   $a1, $a1, %lo(setting)
        jal     0x1320c0                        # sceMcRead(fd, buffer, 16)
        addiu   $a2, $zero, 16
        bnez    $v0, rs_close
        nop
        jal     mc_wait
        nop
        sw      $v0, 16($sp)
rs_close:
        jal     0x131e70                        # sceMcClose(fd)
        move    $a0, $s0
        bnez    $v0, rs_check
        nop
        jal     mc_wait
        nop
rs_check:
        lw      $t0, 16($sp)
        addiu   $t1, $zero, 16
        bne     $t0, $t1, rs_no
        lui     $t2, %hi(setting)
        addiu   $t2, $t2, %lo(setting)
        lui     $t3, 0x2000                     # uncached view of the DMA target
        or      $t2, $t2, $t3
        lw      $t0, 0($t2)
        li      $t1, 0x474c485a                 # 'ZHLG'
        bne     $t0, $t1, rs_no
        lw      $t0, 4($t2)                     # version 1 or 2
        addiu   $t1, $zero, 1
        beq     $t0, $t1, 1f
        addiu   $t1, $zero, 2
        bne     $t0, $t1, rs_no
        nop
1:      lw      $t0, 8($t2)
        lw      $t1, 12($t2)
        nor     $t1, $t1, $zero
        bne     $t0, $t1, rs_no
        srl     $t1, $t0, 8                     # plain zero -> bit 0
        andi    $t1, $t1, 1
        srl     $t3, $t0, 15                    # Japanese quotes (bit 16) -> bit 1
        andi    $t3, $t3, 2
        or      $t1, $t1, $t3
        lui     $t3, %hi(disp)
        sw      $t1, %lo(disp)($t3)
        b       rs_ret
        andi    $v0, $t0, 1
rs_no:  move    $v0, $zero
rs_ret: ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        jr      $ra
        addiu   $sp, $sp, 48

# mc_wait() -> result of the pending libmc command (sceMcSync mode 0 blocks).
mc_wait:
        addiu   $sp, $sp, -32
        sd      $ra, 0($sp)
        move    $a0, $zero
        addiu   $a1, $sp, 16
        jal     0x132350
        addiu   $a2, $sp, 20
        lw      $v0, 20($sp)
        ld      $ra, 0($sp)
        jr      $ra
        addiu   $sp, $sp, 32

# ==== title menu: SELECT opens the settings panel =========================================================
# Replaces `jal 0x154fb0` at 0x155cf8 (title mode handler; a0 = draw packet, returns the advanced packet).
# Idle: SELECT pressed while the menu waits for input (substate gp-0x7a2c == 3) opens the game's own message
# box (0x36bbe0 create, 0x36bc20 set message, 0x36bc30 input, 0x36bcc0 draw, 0x36bd50 destroy) as a panel of
# three settings: language (after a restart), digit zero and dialogue quotes (immediately). Up/down picks a
# row, left/right changes it, circle saves to the card, cross or triangle closes. While it is open the title
# still animates but sees no pressed/repeat edges; the box is drawn after it.
        .globl title_hook
title_hook:
        addiu   $sp, $sp, -64
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        lui     $s1, %hi(dlg_state)
        lw      $t0, %lo(dlg_state)($s1)
        bnez    $t0, th_active
        nop
        lhu     $t1, -0x7a2c($gp)               # title substate
        addiu   $t2, $zero, 3
        bne     $t1, $t2, th_title
        lui     $t3, 0x5a
        lhu     $t3, -0x3db2($t3)               # 0x59c24e: pressed this frame
        andi    $t3, $t3, 0x0100                # SELECT
        beqz    $t3, th_title
        nop
        sd      $a0, 24($sp)
        jal     open_panel
        nop
        ld      $a0, 24($sp)
th_title:
        jal     0x154fb0
        nop
        b       th_ret
        nop
th_active:
        lui     $t9, 0x5a
        lhu     $t2, -0x3db2($t9)               # pressed edges
        lhu     $t3, -0x3dae($t9)               # repeat edges
        sh      $t2, 34($sp)
        sh      $t3, 36($sp)
        sh      $zero, -0x3db2($t9)
        jal     0x154fb0
        sh      $zero, -0x3dae($t9)
        move    $s0, $v0
        lw      $t0, %lo(dlg_state)($s1)
        addiu   $t1, $zero, 1
        bne     $t0, $t1, 1f
        lui     $a0, 0x5a
        jal     0x36bc30                        # panel: the box takes in new text, sees no edges (handled below)
        addiu   $a0, $a0, -0x3f00
1:      lui     $t9, 0x5a
        lhu     $t2, 34($sp)
        lhu     $t3, 36($sp)
        sh      $t2, -0x3db2($t9)
        sh      $t3, -0x3dae($t9)
        lw      $t0, %lo(dlg_state)($s1)
        addiu   $t1, $zero, 1
        bne     $t0, $t1, th_result
        nop
        jal     panel_input                     # -1: close
        lhu     $a0, 34($sp)
        bltz    $v0, th_close
        nop
        b       th_draw
        nop
th_result:
        lui     $a0, 0x5a
        jal     0x36bc30                        # result line: any answer closes
        addiu   $a0, $a0, -0x3f00               # 0x59c100 pad state
        beqz    $v0, th_draw
        nop
th_close:
        jal     0x36bd50
        nop
        jal     restore_msg
        nop
        sw      $zero, %lo(dlg_state)($s1)
        b       th_ret
        move    $v0, $s0
th_draw:
        move    $a0, $s0
        addiu   $a1, $zero, -0x2f               # centred on the 640-wide title (mc screens use -0x3a)
        addiu   $a2, $zero, -0x2e
        jal     0x36bcc0
        move    $a3, $zero
        lw      $t0, %lo(dlg_state)($s1)
        addiu   $t1, $zero, 1
        bne     $t0, $t1, 2f                    # result line: no button icons
        move    $s0, $v0
        move    $a0, $v0                        # panel hint row: the game's ○ / × button sprites (KVP styles)
        addiu   $a1, $zero, ICON_OK
        jal     draw_icon
        addiu   $a2, $zero, ICON_OK_X
        move    $a0, $v0
        addiu   $a1, $zero, ICON_CANCEL
        jal     draw_icon
        addiu   $a2, $zero, ICON_CANCEL_X
        move    $s0, $v0
2:      jal     0x13ac90                        # request this frame's text pass (the box lines)
        nop
        move    $v0, $s0
th_ret: ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        jr      $ra
        addiu   $sp, $sp, 64

# draw_icon(pkt, style, x) -> pkt: KVP style sprite at (x, ICON_Y), full brightness (0x36B330 t0 = 0, t1 = t2 = 128).
draw_icon:
        addiu   $a3, $zero, ICON_Y
        move    $t0, $zero
        addiu   $t1, $zero, 128
        j       0x36b330
        move    $t2, $t1

open_panel:
        addiu   $sp, $sp, -16
        sd      $ra, 0($sp)
        lui     $t9, %hi(panel)
        addiu   $t9, $t9, %lo(panel)
        sw      $zero, 0($t9)                   # cursor on the language row
        lui     $t0, %hi(pending)
        lw      $t1, %lo(pending)($t0)
        bgez    $t1, 1f
        nop
        lui     $t2, %hi(lang)
        lw      $t1, %lo(lang)($t2)             # nothing saved this session: the language running now
1:      sw      $t1, 4($t9)
        lui     $t0, %hi(disp)
        lw      $t1, %lo(disp)($t0)
        andi    $t2, $t1, 1
        sw      $t2, 8($t9)
        srl     $t2, $t1, 1
        andi    $t2, $t2, 1
        jal     0x36bbe0                        # create the box
        sw      $t2, 12($t9)
        jal     show_panel
        nop
        addiu   $t1, $zero, 1
        lui     $t0, %hi(dlg_state)
        sw      $t1, %lo(dlg_state)($t0)
        ld      $ra, 0($sp)
        jr      $ra
        addiu   $sp, $sp, 16

# panel_input(pressed) -> -1 to close, 0 otherwise. Pad bits: up 0x1000, right 0x2000, down 0x4000,
# left 0x8000, triangle 0x10, circle 0x20, cross 0x40.
panel_input:
        addiu   $sp, $sp, -16
        sd      $ra, 0($sp)
        lui     $t9, %hi(panel)
        addiu   $t9, $t9, %lo(panel)
        andi    $t0, $a0, 0x0050                # cross / triangle
        bnez    $t0, pi_close
        andi    $t0, $a0, 0x0020                # circle
        bnez    $t0, pi_save
        lw      $t1, 0($t9)                     # cursor row
        andi    $t0, $a0, 0x1000                # up: row + 2 (mod 3)
        bnez    $t0, pi_row
        addiu   $t2, $t1, 2
        andi    $t0, $a0, 0x4000                # down: row + 1
        bnez    $t0, pi_row
        addiu   $t2, $t1, 1
        andi    $t0, $a0, 0xa000                # left / right: flip the row's value
        beqz    $t0, pi_keep
        sll     $t2, $t1, 2
        addu    $t2, $t9, $t2
        lw      $t3, 4($t2)
        xori    $t3, $t3, 1
        b       pi_show
        sw      $t3, 4($t2)
pi_row: sltiu   $t3, $t2, 3
        bnez    $t3, 1f
        nop
        addiu   $t2, $t2, -3
1:      sw      $t2, 0($t9)
pi_show:
        jal     show_panel
        nop
pi_keep:
        move    $v0, $zero
pi_ret: ld      $ra, 0($sp)
        jr      $ra
        addiu   $sp, $sp, 16
pi_close:
        b       pi_ret
        addiu   $v0, $zero, -1
pi_save:
        jal     write_setting
        nop
        beqz    $v0, 2f
        nop
        lui     $t9, %hi(panel)                 # saved: the language waits for a restart, the look is now
        addiu   $t9, $t9, %lo(panel)
        lw      $t1, 4($t9)
        lui     $t0, %hi(pending)
        sw      $t1, %lo(pending)($t0)
        lw      $t1, 8($t9)
        lw      $t2, 12($t9)
        sll     $t2, $t2, 1
        or      $t1, $t1, $t2
        lui     $t0, %hi(disp)
        sw      $t1, %lo(disp)($t0)
        lui     $t0, %hi(OPTIONS)
        sw      $t1, %lo(OPTIONS)($t0)
        lui     $a2, %hi(attr_ok)
        addiu   $a2, $a2, %lo(attr_ok)
        b       3f
        addiu   $a0, $zero, 12                  # saved
2:      lui     $a2, %hi(attr_fail)
        addiu   $a2, $a2, %lo(attr_fail)
        addiu   $a0, $zero, 13                  # write failed
3:      sd      $a2, 8($sp)
        jal     pick_msg
        nop
        move    $a1, $v0
        ld      $a2, 8($sp)
        jal     set_msg
        addiu   $a0, $zero, 22
        addiu   $t1, $zero, 2
        lui     $t0, %hi(dlg_state)
        sw      $t1, %lo(dlg_state)($t0)
        b       pi_ret
        move    $v0, $zero

# show_panel(): rebuild the panel text (cursor, label, value per row, then the key hint) and show it.
show_panel:
        addiu   $sp, $sp, -32
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        lui     $s0, %hi(panel_buf)             # append() writes at s0
        addiu   $s0, $s0, %lo(panel_buf)
        move    $s1, $zero                      # row
sp_row: lui     $t9, %hi(panel)
        lw      $t0, %lo(panel)($t9)
        bne     $t0, $s1, 1f
        addiu   $a0, $zero, 1                   # blank of the cursor width
        move    $a0, $zero                      # cursor ⇒
1:      jal     append
        nop
        jal     append
        addiu   $a0, $s1, 2                     # label
        lui     $t9, %hi(panel)
        addiu   $t9, $t9, %lo(panel)
        sll     $t0, $s1, 2
        addu    $t0, $t9, $t0
        lw      $t1, 4($t0)
        sll     $a0, $s1, 1
        addiu   $a0, $a0, 5
        jal     append
        addu    $a0, $a0, $t1                   # value
        jal     append
        addiu   $a0, $zero, 14                  # line break
        addiu   $s1, $s1, 1
        sltiu   $t0, $s1, 3
        bnez    $t0, sp_row
        nop
        jal     append
        addiu   $a0, $zero, 11                  # key hint
        sb      $zero, 0($s0)
        lui     $a1, %hi(panel_buf)
        addiu   $a1, $a1, %lo(panel_buf)
        lui     $a2, %hi(attr_panel)
        addiu   $a2, $a2, %lo(attr_panel)
        jal     set_msg
        addiu   $a0, $zero, 22
        ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        jr      $ra
        addiu   $sp, $sp, 32

# append(index): copy fragment `index` (pick_msg) to s0 and advance s0 (show_panel's write pointer).
append:
        addiu   $sp, $sp, -16
        sd      $ra, 0($sp)
        jal     pick_msg
        nop
1:      lbu     $t0, 0($v0)
        beqz    $t0, 2f
        nop
        sb      $t0, 0($s0)
        addiu   $v0, $v0, 1
        b       1b
        addiu   $s0, $s0, 1
2:      ld      $ra, 0($sp)
        jr      $ra
        addiu   $sp, $sp, 16

# pick_msg(index) -> text fragment in the language on screen (lang word), MSG_KEYS order in assemble_dual.py.
# Each language's text uses its own codebook.
pick_msg:
        lui     $t0, %hi(lang)
        lw      $t0, %lo(lang)($t0)
        sll     $t0, $t0, 5                     # lang * 32 (16 halfword offsets a language)
        sll     $a0, $a0, 1
        addu    $t0, $t0, $a0
        lui     $t1, %hi(msg_table)
        addiu   $t1, $t1, %lo(msg_table)
        addu    $t1, $t1, $t0
        lhu     $v0, 0($t1)
        lui     $t1, %hi(msg_base)
        addiu   $t1, $t1, %lo(msg_base)
        jr      $ra
        addu    $v0, $v0, $t1

# set_msg(-, text, attr7): lend a message slot (id alternating 22 / 21) our text and attributes (the box reads the text table
# while it draws, so the slot stays lent until restore_msg) and select it.
set_msg:
        lui     $t0, %hi(msg_id)                # the box ignores a set to the id it shows: alternate 22 / 21
        lw      $a0, %lo(msg_id)($t0)
        xori    $a0, $a0, 3
        sw      $a0, %lo(msg_id)($t0)
        addiu   $sp, $sp, -48
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        sd      $a0, 24($sp)
        sd      $a1, 32($sp)
        jal     restore_msg
        sd      $a2, 40($sp)
        ld      $a0, 24($sp)
        ld      $a1, 32($sp)
        ld      $a2, 40($sp)
        sll     $t0, $a0, 2
        lui     $s0, 0x41                       # 0x4171f0: message text pointers
        addiu   $s0, $s0, 0x71f0
        addu    $s0, $s0, $t0
        sll     $t0, $a0, 3
        subu    $t0, $t0, $a0                   # id * 7
        lui     $s1, 0x43                       # 0x42bf90: message attributes
        addiu   $s1, $s1, -0x4070
        addu    $s1, $s1, $t0
        lui     $t9, %hi(lent)
        addiu   $t9, $t9, %lo(lent)
        sw      $s0, 0($t9)                     # lent text slot
        sw      $s1, 4($t9)                     # lent attribute slot
        lw      $t1, 0($s0)
        sw      $t1, 8($t9)                     # original pointer
        sw      $a1, 0($s0)
        move    $t2, $zero
5:      addu    $t3, $s1, $t2
        lbu     $t4, 0($t3)
        addu    $t5, $t9, $t2
        sb      $t4, 12($t5)                    # original attributes
        addu    $t5, $a2, $t2
        lbu     $t4, 0($t5)
        sb      $t4, 0($t3)
        addiu   $t2, $t2, 1
        sltiu   $t3, $t2, 7
        bnez    $t3, 5b
        nop
        jal     0x36bc20
        nop
        ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        jr      $ra
        addiu   $sp, $sp, 48

# restore_msg(): give a lent message slot back.
restore_msg:
        lui     $t9, %hi(lent)
        addiu   $t9, $t9, %lo(lent)
        lw      $t0, 0($t9)
        beqz    $t0, 7f
        lw      $t1, 8($t9)
        sw      $t1, 0($t0)
        lw      $t3, 4($t9)
        move    $t2, $zero
6:      addu    $t5, $t9, $t2
        lbu     $t4, 12($t5)
        addu    $t5, $t3, $t2
        sb      $t4, 0($t5)
        addiu   $t2, $t2, 1
        sltiu   $t5, $t2, 7
        bnez    $t5, 6b
        nop
        sw      $zero, 0($t9)
7:      jr      $ra
        nop

# write_setting() -> 1 when /BISLPS-25887L/LANG.BIN now holds the panel's values. A newly created directory also gets
# icon.sys (the executable's template at 0x414080 with our title lent in) and the save icon (0x414450), so
# the console's card browser shows it as game data instead of corrupt data.
write_setting:
        addiu   $sp, $sp, -112
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        addiu   $a0, $zero, 1                   # libmc idle? (sceMcSync(1) == -1)
        addiu   $a1, $sp, 24
        jal     0x132350
        addiu   $a2, $sp, 28
        addiu   $t0, $zero, -1
        bne     $v0, $t0, ws_no
        move    $a0, $zero
        move    $a1, $zero
        lui     $a2, %hi(lang_dir)
        jal     0x131e38                        # mkdir (sceMcOpen mode 0x40)
        addiu   $a2, $a2, %lo(lang_dir)
        bnez    $v0, ws_no
        nop
        jal     mc_wait
        nop
        addiu   $t0, $zero, -4
        beq     $v0, $t0, ws_lang               # -4: already there
        nop
        bnez    $v0, ws_no
        nop
        # new directory: icon.sys with our title (bytes 0xc0.., line break at byte 6), then the icon
        lui     $s1, 0x41
        addiu   $s1, $s1, 0x4080                # 0x414080 icon.sys template
        lhu     $t0, 6($s1)
        sh      $t0, 104($sp)
        move    $t2, $zero
1:      addu    $t3, $s1, $t2                   # lend 64 title bytes
        lbu     $t4, 0xc0($t3)
        addu    $t5, $sp, $t2
        sb      $t4, 40($t5)
        lui     $t5, %hi(icon_title)
        addiu   $t5, $t5, %lo(icon_title)
        addu    $t5, $t5, $t2
        lbu     $t4, 0($t5)
        sb      $t4, 0xc0($t3)
        addiu   $t2, $t2, 1
        sltiu   $t3, $t2, 64
        bnez    $t3, 1b
        nop
        addiu   $t0, $zero, 22                  # second line starts after スーパーロボット大戦Ｚ
        sh      $t0, 6($s1)
        lui     $a0, %hi(icon_sys_path)
        addiu   $a0, $a0, %lo(icon_sys_path)
        move    $a1, $s1
        jal     write_file
        addiu   $a2, $zero, 964
        move    $s0, $v0
        lhu     $t0, 104($sp)                   # give the template back
        sh      $t0, 6($s1)
        move    $t2, $zero
2:      addu    $t5, $sp, $t2
        lbu     $t4, 40($t5)
        addu    $t3, $s1, $t2
        sb      $t4, 0xc0($t3)
        addiu   $t2, $t2, 1
        sltiu   $t3, $t2, 64
        bnez    $t3, 2b
        nop
        beqz    $s0, ws_no
        lui     $a0, %hi(icon_path)
        addiu   $a0, $a0, %lo(icon_path)
        lui     $a1, 0x41
        addiu   $a1, $a1, 0x4450                # 0x414450 save icon model
        jal     write_file
        addiu   $a2, $zero, 11664
        beqz    $v0, ws_no
        nop
ws_lang:
        lui     $t0, %hi(setting)
        addiu   $t0, $t0, %lo(setting)
        li      $t1, 0x474c485a                 # 'ZHLG'
        sw      $t1, 0($t0)
        addiu   $t1, $zero, 2                   # version 2: lang | plain zero << 8 | Japanese quotes << 16
        sw      $t1, 4($t0)
        lui     $t2, %hi(panel)
        addiu   $t2, $t2, %lo(panel)
        lw      $t1, 4($t2)
        lw      $t3, 8($t2)
        sll     $t3, $t3, 8
        or      $t1, $t1, $t3
        lw      $t3, 12($t2)
        sll     $t3, $t3, 16
        or      $t1, $t1, $t3
        sw      $t1, 8($t0)
        nor     $t1, $t1, $zero
        sw      $t1, 12($t0)
        lui     $a0, %hi(lang_path)
        addiu   $a0, $a0, %lo(lang_path)
        move    $a1, $t0
        jal     write_file
        addiu   $a2, $zero, 16
        b       ws_ret
        nop
ws_no:  move    $v0, $zero
ws_ret: ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        jr      $ra
        addiu   $sp, $sp, 112

# write_file(path, buffer, length) -> 1 when the whole buffer was written (create / write / close).
write_file:
        addiu   $sp, $sp, -64
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        sd      $s2, 24($sp)
        move    $s1, $a1
        move    $s2, $a2
        move    $a2, $a0
        move    $a0, $zero
        move    $a1, $zero
        jal     0x131d10                        # sceMcOpen(0, 0, path, CREAT | WRONLY)
        addiu   $a3, $zero, 0x202
        bnez    $v0, wf_no
        nop
        jal     mc_wait
        nop
        bltz    $v0, wf_no
        move    $s0, $v0
        sw      $zero, 32($sp)
        move    $a0, $s0
        move    $a1, $s1
        jal     0x1321d8                        # sceMcWrite(fd, buffer, length)
        move    $a2, $s2
        bnez    $v0, 3f
        nop
        jal     mc_wait
        nop
        sw      $v0, 32($sp)
3:      jal     0x131e70                        # sceMcClose(fd)
        move    $a0, $s0
        bnez    $v0, wf_no
        nop
        jal     mc_wait
        nop
        bnez    $v0, wf_no
        lw      $t0, 32($sp)
        bne     $t0, $s2, wf_no
        nop
        b       wf_ret
        addiu   $v0, $zero, 1
wf_no:  move    $v0, $zero
wf_ret: ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        ld      $s2, 24($sp)
        jr      $ra
        addiu   $sp, $sp, 64

# read_sectors(lba, sectors, buffer): 0x1391b0 without its heap allocation (same CD calls and retries).
read_sectors:
        addiu   $sp, $sp, -48
        sd      $ra, 0($sp)
        sd      $s0, 8($sp)
        sd      $s1, 16($sp)
        sd      $s2, 24($sp)
        move    $s0, $a0
        move    $s1, $a1
        move    $s2, $a2
        jal     0x12f698
        move    $a0, $zero
r1:     lui     $a3, 0x47
        move    $a0, $s0
        move    $a1, $s1
        move    $a2, $s2
        jal     0x12f8b8                # sceCdRead(lba, sectors, buffer, mode 0x46df10)
        addiu   $a3, $a3, -0x20f0
        addiu   $v1, $zero, 1
        bne     $v0, $v1, r1
        nop
        jal     0x12ee80                # sync
        move    $a0, $zero
        bnez    $v0, r1
        nop
        jal     0x12fa98                # error status
        nop
        beqz    $v0, r2
        nop
        jal     0x12f698
        move    $a0, $zero
        b       r1
        nop
r2:     ld      $ra, 0($sp)
        ld      $s0, 8($sp)
        ld      $s1, 16($sp)
        ld      $s2, 24($sp)
        jr      $ra
        addiu   $sp, $sp, 48
        .align  6
setting:                                # LANG.BIN buffer (cache-line aligned for the card DMA); also the panel
panel_buf:                              # text (84 bytes at most), rebuilt on every change and never in use while
        .space  84                      # the card is read (boot) or written (the result line replaces the panel)
lang_path:
        .asciz  "/BISLPS-25887L/LANG.BIN"
lang_dir:
        .asciz  "/BISLPS-25887L"
icon_sys_path:
        .asciz  "/BISLPS-25887L/icon.sys"
icon_path:
        .asciz  "/BISLPS-25887L/a20.ico"
        .include "icon_title.inc"                               # icon_title: 64 bytes Shift-JIS
attr_panel:
        .byte   0x02, 0x04, 0xff, 0x05, 0x05, 0x05, 0x05        # notice, 4 lines (3 settings + key hint)
attr_ok:
        .byte   0x02, 0x02, 0xff, 0x05, 0x05, 0x05, 0x05        # notice, 2 lines
attr_fail:
        .byte   0x01, 0x01, 0xff, 0x05, 0x05, 0x05, 0x05        # Caution, 1 line
        .include "messages.inc"                                 # fragments + msg_table (16 halfword offsets a language)
        .align  2
dlg_state:
        .word   0                       # 0 closed, 1 settings panel, 2 result line
pending:
        .word   -1                      # language the card now asks for (-1: not read yet = lang)
panel:  .word   0, 0, 0, 0              # cursor row, language, plain zero, Japanese quotes
disp:   .word   0                       # display flags in use: bit 0 plain zero, bit 1 Japanese quotes
msg_id: .word   22
lent:   .word   0, 0, 0, 0, 0           # text slot, attribute slot, original pointer, original attributes (7)
        .align  2
        .globl  lang
lang:   .word   0                       # 0 = Simplified, 1 = Traditional (for later consumers)
