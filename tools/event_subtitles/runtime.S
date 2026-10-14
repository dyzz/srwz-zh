/* Original/The Best native map subtitle overlay. No scene/menu/script edits. */
.set noreorder
.set noat
.set mips3
.include "profile.inc"
.text
.org 0x700
.globl caption_draw_caption
caption_draw_caption:
    addiu   $sp,$sp,-0x30
    sd      $ra,0x28($sp)
    sd      $s0,0x20($sp)
    sd      $s1,0x18($sp)
    sd      $s2,0x10($sp)
    daddu   $s0,$a0,$zero
    lui     $s1,%hi(EFFECT_POOL)
    addiu   $s1,$s1,%lo(EFFECT_POOL)
    addiu   $t7,$zero,40
caption_find_effect:
    lbu     $t0,0x3c($s1)
    beq     $t0,$zero,caption_next_effect
    nop
    lw      $t0,0($s1)
    beq     $t0,$zero,caption_next_effect
    nop
    lhu     $t1,0x2c($s1)
    lhu     $t2,0x32($s1)
    lui     $s2,%hi(PAYLOAD_BASE)
    ori     $s2,$s2,0x5800
caption_find_line:
    lw      $t0,0($s2)
    addiu   $t3,$zero,-1
    beq     $t0,$t3,caption_next_effect
    nop
    bne     $t0,$t1,caption_next_line
    nop
    lw      $t0,4($s2)
    sltu    $t0,$t2,$t0
    bne     $t0,$zero,caption_next_line
    nop
    lw      $t0,8($s2)
    sltu    $t0,$t2,$t0
    bne     $t0,$zero,caption_draw
    nop
caption_next_line:
    b       caption_find_line
    addiu   $s2,$s2,20
caption_next_effect:
    addiu   $s1,$s1,0x50
    addiu   $t7,$t7,-1
    bne     $t7,$zero,caption_find_effect
    nop
    b       caption_return
    nop
caption_draw:
    lui     $t0,%hi(PAYLOAD_BASE)
    lw      $t1,0x1f00($t0)
    addiu   $t1,$t1,1
    sw      $t1,0x1f00($t0)
    lhu     $t1,0x2c($s1)
    sw      $t1,0x1f04($t0)
    lhu     $t1,0x32($s1)
    sw      $t1,0x1f08($t0)
    addiu   $t1,$zero,1
    sw      $t1,0x1f0c($t0)
    /* Save this field's clean display, keyed by its native framebuffer. */
    lw      $t0,0($s2)
    addiu   $t1,$zero,257
    bne     $t0,$t1,caption_history_saved
    nop
    lui     $t0,%hi(SCREEN_EFFECT_ENABLED)
    lbu     $t0,%lo(SCREEN_EFFECT_ENABLED)($t0)
    beq     $t0,$zero,caption_history_saved
    nop
    daddu   $a0,$s0,$zero
    lui     $t0,%hi(FRAME_PARITY)
    lw      $t0,%lo(FRAME_PARITY)($t0)
    andi    $t0,$t0,1
    daddu   $a1,$zero,$zero
    ori     $a2,$zero,0x3d00
    ori     $t1,$zero,1
    beq     $t0,$zero,caption_backup_target
    nop
    ori     $a1,$zero,0x08c0
    ori     $a2,$zero,0x3e00
    ori     $t1,$zero,2
caption_backup_target:
    lui     $t0,%hi(PAYLOAD_BASE)
    lw      $t2,0x1f10($t0)
    or      $t2,$t2,$t1
    sw      $t2,0x1f10($t0)
    jal     caption_copy_caption_rect
    daddu   $a3,$zero,$zero
    daddu   $s0,$v0,$zero
caption_history_saved:
    lui     $t0,%hi(PAYLOAD_BASE)
    ori     $t0,$t0,0x1d00
    daddu   $t1,$s1,$zero
    addiu   $t2,$zero,20
caption_copy_slot:
    lw      $t3,0($t1)
    sw      $t3,0($t0)
    addiu   $t0,$t0,4
    addiu   $t1,$t1,4
    addiu   $t2,$t2,-1
    bne     $t2,$zero,caption_copy_slot
    nop
    lui     $s1,%hi(PAYLOAD_BASE)
    ori     $s1,$s1,0x1d00
    lui     $t0,%hi(PAYLOAD_BASE)
    ori     $t0,$t0,0x1c00
    sw      $t0,0($s1)
    addiu   $t0,$t0,0x10
    sw      $t0,4($s1)
    sh      $zero,0x32($s1)
    addiu   $t0,$zero,2
    sh      $t0,0x34($s1)
    /* Screen coordinates are centred at GS (2048,2048), while the
       640 x 224 viewport starts at (1728,1936). */
    sw      $zero,0x10($s1)
    sw      $zero,0x14($s1)
    lui     $t0,0x3f80       /* 1.0 */
    sw      $t0,0x20($s1)
    lui     $t0,0x8080
    ori     $t0,$t0,0x8080
    sw      $t0,0x24($s1)   /* independent of the actor's colour/fade */
    addiu   $t0,$zero,1
    sb      $t0,0x3d($s1)   /* native screen-space primitive, Z test off */
    sb      $zero,0x41($s1)
    lui     $t0,%hi(PAYLOAD_BASE)
    ori     $t0,$t0,0x1c2c /* single quad, after 20-byte header + four offsets */
    lw      $t1,12($s2)
    sh      $t1,38($t0)     /* v of this caption line */
    srl     $t1,$t1,16
    sh      $t1,40($t0)     /* texture width of this effect's caption atlas */
    lw      $t1,16($s2)
    sh      $t1,46($t0)
    /* Late screen effects leave XYOFFSET at zero. Restore the native viewport
     * for this screen-space quad as well as its full-screen scissor. */
    addiu   $t0,$zero,0x1000
    dsll    $t0,$t0,48
    ori     $t0,$t0,0x8002
    sd      $t0,0($s0)
    addiu   $t0,$zero,14
    sd      $t0,8($s0)
    lui     $t1,0x00df      /* SCISSOR y=0..223, x=0..639 */
    dsll32  $t1,$t1,0
    lui     $t0,0x027f
    or      $t1,$t1,$t0
    sd      $t1,16($s0)
    addiu   $t0,$zero,0x40
    sd      $t0,24($s0)
    /* XYOFFSET_1 = (1728, 1936) in both fields. A per-field half-row offset
       (as the native packets use) combs the caption in ARMSX2/PCSX2 upscaled
       output (2026-10-14 field tests), so both fields draw the same image. */
    ori     $t1,$zero,0x7900
    dsll32  $t1,$t1,0
    ori     $t1,$t1,0x6c00
    sd      $t1,32($s0)
    addiu   $t0,$zero,0x18
    sd      $t0,40($s0)
    addiu   $a0,$s0,48
    daddu   $a1,$s1,$zero
    daddu   $a2,$zero,$zero
    jal     DRAW_QUAD       /* final overlay, outside the scene's post effects */
    daddu   $a3,$zero,$zero
    /* The native sprite path writes TEX1_1 = 0 (nearest). Filter the caption
       bilinearly: the 2-rows-per-native-row atlas then averages at native
       resolution and magnifies smoothly in upscaled renderers. */
    addiu   $t0,$s0,48
    addiu   $t3,$zero,16
caption_tex1_scan:
    ld      $t1,8($t0)
    addiu   $t2,$zero,0x14  /* A+D register TEX1_1 */
    bne     $t1,$t2,caption_tex1_next
    nop
    ld      $t1,0($t0)
    ori     $t1,$t1,0x60    /* MMAG = MMIN = LINEAR */
    b       caption_tex1_done
    sd      $t1,0($t0)
caption_tex1_next:
    addiu   $t3,$t3,-1
    bne     $t3,$zero,caption_tex1_scan
    addiu   $t0,$t0,16
caption_tex1_done:
    daddu   $s0,$v0,$zero
caption_return:
    daddu   $v0,$s0,$zero
    ld      $s2,0x10($sp)
    ld      $s1,0x18($sp)
    ld      $s0,0x20($sp)
    ld      $ra,0x28($sp)
    jr      $ra
    addiu   $sp,$sp,0x30

.org 0xa00
.globl caption_final_draw
caption_final_draw:
    addiu   $sp,$sp,-0x30
    sd      $ra,0x28($sp)
    sd      $s0,0x20($sp)
    jal     NATIVE_POLL       /* original poll after late screen/post-effect passes */
    nop
    jal     caption_finish_feedback
    nop
    lui     $s0,%hi(PACKET_BASE + 0x8000)
    addiu   $s0,$s0,-0x8000 /* private 0x828000 packet */
    lui     $t0,%hi(PAYLOAD_BASE)
    sw      $zero,0x1f0c($t0)
    jal     caption_draw_caption
    daddu   $a0,$s0,$zero
    subu    $s0,$v0,$s0
    beq     $s0,$zero,final_draw_return
    nop
    jal     FLUSH_CACHE       /* FlushCache(0), before the final direct GIF DMA */
    daddu   $a0,$zero,$zero
    lui     $t0,0x1001
    lui     $t1,%hi(PACKET_BASE + 0x8000)
    addiu   $t1,$t1,-0x8000
    sw      $t1,-0x5ff0($t0) /* GIF MADR */
    srl     $s0,$s0,4
    sw      $s0,-0x5fe0($t0) /* GIF QWC */
    addiu   $t1,$zero,0x101
    sw      $t1,-0x6000($t0) /* GIF CHCR, normal transfer */
    jal     WAIT_GIF       /* finish overlay before the frame is presented */
    nop
final_draw_return:
    ld      $s0,0x20($sp)
    ld      $ra,0x28($sp)
    jr      $ra
    addiu   $sp,$sp,0x30

.org 0xc00
caption_copy_caption_rect:
    ori     $t0,$zero,0x1000
    dsll    $t0,$t0,48
    ori     $t0,$t0,0x8005
    sd      $t0,0($a0)
    addiu   $t0,$zero,14
    sd      $t0,8($a0)
    dsll32  $t0,$a2,0
    or      $t0,$t0,$a1
    bne     $a3,$zero,copy_rect_restore
    nop
    ori     $t1,$zero,8
    dsll    $t1,$t1,48
    lui     $t2,10
    or      $t1,$t1,$t2
    lui     $t2,194
    ori     $t2,$t2,64
    b       copy_rect_fields
    nop
copy_rect_restore:
    ori     $t1,$zero,10
    dsll    $t1,$t1,48
    lui     $t2,8
    or      $t1,$t1,$t2
    lui     $t2,194
    ori     $t2,$t2,64
    dsll32  $t2,$t2,0
copy_rect_fields:
    or      $t0,$t0,$t1
    sd      $t0,16($a0)
    ori     $t0,$zero,0x50
    sd      $t0,24($a0)
    sd      $t2,32($a0)
    ori     $t0,$zero,0x51
    sd      $t0,40($a0)
    ori     $t0,$zero,20
    dsll32  $t0,$t0,0
    ori     $t0,$t0,512
    sd      $t0,48($a0)
    ori     $t0,$zero,0x52
    sd      $t0,56($a0)
    ori     $t0,$zero,2
    sd      $t0,64($a0)
    ori     $t0,$zero,0x53
    sd      $t0,72($a0)
    sd      $zero,80($a0)
    ori     $t0,$zero,0x3f
    sd      $t0,88($a0)
    jr      $ra
    addiu   $v0,$a0,96

.org 0xd00
caption_submit_copy:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    lui     $a0,%hi(PACKET_BASE + 0x8000)
    addiu   $a0,$a0,-0x8000
    jal     caption_copy_caption_rect
    nop
    jal     FLUSH_CACHE
    daddu   $a0,$zero,$zero
    lui     $t0,0x1001
    lui     $t1,%hi(PACKET_BASE + 0x8000)
    addiu   $t1,$t1,-0x8000
    sw      $t1,-0x5ff0($t0)
    addiu   $t1,$zero,6
    sw      $t1,-0x5fe0($t0)
    addiu   $t1,$zero,0x101
    sw      $t1,-0x6000($t0)
    jal     WAIT_GIF
    nop
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20

.org 0xe00
caption_prepare_feedback:
    addiu   $sp,$sp,-0x40
    sd      $ra,0x38($sp)
    sd      $s0,0x30($sp)
    sd      $s1,0x28($sp)
    sd      $s2,0x20($sp)
    jal     FRAME_INFO
    nop
    daddu   $s0,$v0,$zero
    jal     caption_feedback_active
    nop
    lui     $t0,%hi(PAYLOAD_BASE)
    bne     $v0,$zero,prepare_feedback_enabled
    nop
    sw      $zero,0x1f10($t0)
    sw      $zero,0x1f18($t0)
    b       prepare_feedback_return
    nop
prepare_feedback_enabled:
    lw      $t1,0x1f10($t0)
    beq     $t1,$zero,prepare_feedback_return
    nop
    lw      $t2,0($s0)
    andi    $t2,$t2,1
    ori     $s1,$zero,0x08c0
    ori     $s2,$zero,0x3e00
    ori     $t3,$zero,2
    beq     $t2,$zero,prepare_feedback_source
    nop
    daddu   $s1,$zero,$zero
    ori     $s2,$zero,0x3d00
    ori     $t3,$zero,1
prepare_feedback_source:
    and     $t1,$t1,$t3
    beq     $t1,$zero,prepare_feedback_return
    nop
    sw      $s1,0x1f14($t0)
    ori     $t1,$zero,1
    sw      $t1,0x1f18($t0)
    daddu   $a1,$s1,$zero
    ori     $a2,$zero,0x3f00
    jal     caption_submit_copy
    daddu   $a3,$zero,$zero
    daddu   $a1,$s2,$zero
    daddu   $a2,$s1,$zero
    jal     caption_submit_copy
    ori     $a3,$zero,1
prepare_feedback_return:
    daddu   $v0,$s0,$zero
    ld      $s2,0x20($sp)
    ld      $s1,0x28($sp)
    ld      $s0,0x30($sp)
    ld      $ra,0x38($sp)
    jr      $ra
    addiu   $sp,$sp,0x40

.org 0x1000
caption_finish_feedback:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    lui     $t0,%hi(PAYLOAD_BASE)
    lw      $t1,0x1f18($t0)
    beq     $t1,$zero,finish_feedback_mask
    nop
    sw      $zero,0x1f18($t0)
    ori     $a1,$zero,0x3f00
    lw      $a2,0x1f14($t0)
    jal     caption_submit_copy
    ori     $a3,$zero,1
finish_feedback_mask:
    lui     $t0,%hi(FRAME_PARITY)
    lw      $t0,%lo(FRAME_PARITY)($t0)
    andi    $t0,$t0,1
    ori     $t1,$zero,1
    sllv    $t1,$t1,$t0
    nor     $t1,$t1,$zero
    lui     $t0,%hi(PAYLOAD_BASE)
    lw      $t2,0x1f10($t0)
    and     $t2,$t2,$t1
    sw      $t2,0x1f10($t0)
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20


.org 0x1200
caption_feedback_active:
    lui     $t4,%hi(EFFECT_POOL)
    addiu   $t4,$t4,%lo(EFFECT_POOL)
    ori     $t5,$zero,40
feedback_scan:
    lbu     $t6,0x3c($t4)
    beq     $t6,$zero,feedback_next
    nop
    lhu     $t6,0x2c($t4)
    ori     $t8,$zero,257
    beq     $t6,$t8,feedback_found
    nop
feedback_next:
    addiu   $t4,$t4,0x50
    addiu   $t5,$t5,-1
    bne     $t5,$zero,feedback_scan
    nop
    jr      $ra
    daddu   $v0,$zero,$zero
feedback_found:
    jr      $ra
    ori     $v0,$zero,1
