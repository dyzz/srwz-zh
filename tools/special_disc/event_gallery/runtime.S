/* Native SP event gallery, SLPS_259.20 only.
 * Link .text at 0x00822000 and copy gallery_runtime.bin there.
 * Replace only JAL at 0x00143ea8 with JAL gallery_frame (0x00822100).
 * Existing menu selector callback is 0x00822000.
 * State at 0x00821f00: +0 selected row, +4 phase (0 list, 1 requested,
 * 2 playing, 3 completed), +8 last completed row, +0x10 feedback valid mask,
 * +0x14 temporary source framebuffer, +0x18 pending restoration,
 * +0x20 theater BGM id, +0x24 theater BGM restore pending,
 * +0x28 placeholder-actor table before playback, +0x30 resident map effects
 * loaded for this theater session, +0x40 saved unit flags.
 * Rows select the configuration-generated map/camera/script table at 0x00823c00.
 * Native scripts at 0x00826800. No stage script, save-state or host trigger.
 * Original UI object remains allocated; rendering/input freezes during playback.
 */
.set noreorder
.set noat
.set mips3
/* Caption / copy GIF packets are built here every frame. The 4 KB block at the
   end of the stored payload is reserved; apply.py rejects any data in it. */
.set GALLERY_PACKET, 0x0082F000
.text
.globl gallery_selector
.globl gallery_frame
.globl gallery_finish
.globl gallery_script
.ent gallery_selector
gallery_selector:
    beq     $a3,$zero,selector_return
    nop
    lw      $v0,0x4c($a3)
    lui     $v1,0x0082
    sw      $v0,0x1f00($v1)
    addiu   $v0,$zero,1
    sw      $v0,0x1f04($v1)
selector_return:
    jr      $ra
    daddu   $v0,$zero,$zero
.end gallery_selector

.org 0x100
.ent gallery_frame
gallery_frame:
    lui     $t0,0x0082
    lw      $t1,0x1f04($t0)
    bne     $t1,$zero,frame_active
    nop
frame_native:
    lw      $t1,0x1f24($t0)
    bne     $t1,$zero,frame_restore_bgm
    nop
    j       0x00244ef0
    nop
frame_restore_bgm:
    /* Return the theater's own BGM once the scene's sound request is idle. */
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    sd      $a0,0x10($sp)
    jal     gallery_bgm_restore
    nop
    ld      $a0,0x10($sp)
    ld      $ra,0x18($sp)
    addiu   $sp,$sp,0x20
    j       0x00244ef0
    daddu   $a1,$zero,$zero
frame_active:
    addiu   $t2,$zero,1
    bne     $t1,$t2,frame_save
    nop
    lw      $t2,0x1f00($t0)
    sltiu   $t2,$t2,GALLERY_SCENE_COUNT
    bne     $t2,$zero,frame_save
    nop
    /* Reject only invalid row indices; every catalog row has a native script. */
    sw      $zero,0x1f04($t0)
    b       frame_native
    nop
frame_save:
    addiu   $sp,$sp,-0x50
    sd      $ra,0x48($sp)
    sd      $s0,0x40($sp)
    sd      $s1,0x38($sp)
    sd      $s2,0x30($sp)
    sd      $s3,0x28($sp)
    daddu   $s0,$a0,$zero
    lui     $s1,0x0082
    ori     $s1,$s1,0x1f00
    addiu   $t2,$zero,3
    beq     $t1,$t2,frame_complete
    nop
    addiu   $t2,$zero,1
    bne     $t1,$t2,frame_map
    nop

    addiu   $t2,$zero,2
    sw      $t2,4($s1)
    /* Map initialization changes the framebuffer interpretation. Clear both
     * display buffers first so the last theater frame cannot be presented
     * with the map's pixel format while the stage is loading. */
    jal     gallery_clear_transition
    nop
    jal     gallery_save_roster
    nop
    lw      $t0,0x24($s1)
    bne     $t0,$zero,bgm_owner_kept /* previous return still restoring */
    nop
    lui     $t0,0x005e
    lbu     $t0,-0x4468($t0)  /* 005dbb98 current BGM */
    sw      $t0,0x20($s1)
bgm_owner_kept:
    lui     $t0,0x0063
    lw      $t0,-0x25e4($t0)  /* 0062da1c placeholder-actor table */
    sw      $t0,0x28($s1)
    /* Save visibility flags for compatibility, then suppress all stale actors.
     * The complete roster/unit snapshot also protects temporary scene actors. */
    lui     $t0,0x0061
    ori     $t0,$t0,0x6740
    addiu   $t1,$zero,120
    addiu   $t2,$s1,0x40
save_units:
    lbu     $t3,0x14($t0)
    sb      $t3,0($t2)
    sb      $zero,0x14($t0)
    addiu   $t0,$t0,0xb0
    addiu   $t2,$t2,1
    addiu   $t1,$t1,-1
    bne     $t1,$zero,save_units
    nop
    jal     0x001ac8e0       /* clear active/dynamic effects, stop effect voice */
    nop
    /* Stage initialization loads the resident map effects (unit explosions,
     * appearances; VEFF chunks 1..n) and uploads their texture. The theater
     * never does, so placeholder explosions drew untextured quads. Load them
     * once per theater session; the native loader allocates their block. */
    lui     $t0,0x0063
    lw      $t1,-0x55b0($t0)  /* 0062aa50 theater's resident block, restored on return */
    sw      $t1,0x30($s1)
    jal     0x001ac220       /* native resident map-effect loader (stage init) */
    addiu   $a0,$zero,1
    lui     $t0,0x005a
    lw      $t1,0x3e00($t0)
    beq     $t1,$zero,init_map
    nop
    addiu   $a0,$zero,1
    jal     0x00148a50       /* release any previous loaded map */
    daddu   $a1,$zero,$zero
init_map:
    lw      $t1,0($s1)
    sll     $t1,$t1,5
    lui     $s3,%hi(gallery_scene_table)
    addiu   $s3,$s3,%lo(gallery_scene_table)
    addu    $s3,$s3,$t1
    lui     $t0,0x005a
    lw      $t1,0($s3)
    sw      $t1,0x3db0($t0)
    lw      $a0,4($s3)
    lw      $a1,8($s3)
    lw      $a2,12($s3)
    jal     0x001453f0       /* synchronous native map/camera initialization */
    addiu   $a3,$zero,1
    jal     gallery_initialize_stage_objects
    lw      $a0,0($s1)
    jal     0x00176030       /* hide tactical cursor/selection markers */
    addiu   $a0,$zero,3
    jal     0x00146180
    addiu   $a0,$zero,1
    lw      $a0,16($s3)
    jal     0x0017c290       /* enter independent native event script */
    addiu   $a1,$zero,1
frame_map:
    /* Cache hits can bypass the native shared CCC timeline initialization.
     * Install this gallery scene's unmodified source schedule before rendering.
     * Native effect code still owns exact-frame speech calls and CCC playback.
     */
    lw      $t1,0($s1)
    sll     $t1,$t1,5
    lui     $t0,%hi(gallery_scene_table)
    addiu   $t0,$t0,%lo(gallery_scene_table)
    addu    $t0,$t0,$t1
    lw      $t0,28($t0)
    beq     $t0,$zero,voice_ready
    nop
    lui     $t2,0x0063
    addiu   $t2,$t2,-0x64a0  /* 00629b60 native shared CCC timeline */
    addiu   $t3,$zero,20
copy_voice:
    lw      $t1,0($t0)
    sw      $t1,0($t2)
    addiu   $t0,$t0,4
    addiu   $t2,$t2,4
    addiu   $t3,$t3,-1
    bne     $t3,$zero,copy_voice
    nop
voice_ready:
    lui     $t0,0x005a
    addiu   $t1,$zero,1
    sw      $t1,0x4598($t0)
    sw      $t1,0x45a0($t0)
    jal     0x00140290       /* script poll, camera matrices, map actor rendering */
    daddu   $a0,$s0,$zero
    b       frame_restore
    nop

frame_complete:
    /* All effects have completed before gallery_finish sets phase 3. */
    jal     0x001ac8e0
    nop
    jal     0x001bd060       /* script screen tint off (op 0x13b0 0) */
    nop
    /* The scene's resident map-effect block is no longer referenced (effects
     * cleared above); free it before the saved table/pointers come back. */
    lui     $t0,0x0063
    lw      $a0,-0x55b0($t0)  /* 0062aa50 */
    lw      $t1,0x30($s1)
    beq     $a0,$t1,resident_block_released
    nop
    jal     0x001a1718       /* native heap free */
    nop
resident_block_released:
    lui     $t0,0x0063
    lw      $t0,-0x25e4($t0)
    lw      $a0,0x28($s1)
    beq     $t0,$a0,placeholder_table_restored
    nop
    jal     0x001c0f70       /* reinstall the previous table while the map is loaded */
    nop
placeholder_table_restored:
    addiu   $a0,$zero,1
    jal     0x00148a50       /* release stage models, map buffers and render state */
    daddu   $a1,$zero,$zero
    lui     $t0,0x004d
    sh      $zero,-0x50fc($t0)  /* 004caf04 script active */
    sh      $zero,-0x50f4($t0)  /* 004caf0c script secondary active */
    lui     $t0,0x0062
    sh      $zero,-0x2150($t0)  /* 0061deb0 script opcode */
    sw      $zero,-0x2148($t0)  /* 0061deb8 script pointer */
    lui     $t0,0x004f
    sw      $zero,-0x2930($t0)  /* 004ed6d0 camera movement mode */
    lui     $t0,0x0061
    ori     $t0,$t0,0x6740
    addiu   $t1,$zero,120
    addiu   $t2,$s1,0x40
restore_units:
    lbu     $t3,0($t2)
    sb      $t3,0x14($t0)
    addiu   $t0,$t0,0xb0
    addiu   $t2,$t2,1
    addiu   $t1,$t1,-1
    bne     $t1,$zero,restore_units
    nop
    jal     gallery_restore_roster
    nop
    addiu   $t0,$zero,1
    sw      $t0,0x24($s1)
    /* Reuse the theater object's native VRAM backup/restore implementation.
     * 3274f0 restores and frees all three backups; 3273d0 immediately renews them.
     * The list widget/selection and owner object are not destroyed.
     */
    lui     $t0,0x0076
    lw      $t0,-0x12b0($t0)  /* 0075ed50 event record */
    beq     $t0,$zero,complete_ui
    nop
    lw      $s2,8($t0)
    beq     $s2,$zero,complete_ui
    nop
    jal     0x003274f0
    daddu   $a0,$s2,$zero
    jal     0x003273d0
    daddu   $a0,$s2,$zero
complete_ui:
    lw      $t0,0($s1)
    sw      $t0,8($s1)
    sw      $zero,4($s1)
    daddu   $a0,$s0,$zero
    jal     0x00244ef0       /* automatic return to the same list */
    daddu   $a1,$zero,$zero
frame_restore:
    ld      $s3,0x28($sp)
    ld      $s2,0x30($sp)
    ld      $s1,0x38($sp)
    ld      $s0,0x40($sp)
    ld      $ra,0x48($sp)
    jr      $ra
    addiu   $sp,$sp,0x50
.end gallery_frame

.align 4
.ent gallery_finish
gallery_finish:
    lui     $t0,0x0082
    addiu   $t1,$zero,3
    jr      $ra
    sw      $t1,0x1f04($t0)
.end gallery_finish

.org 0x500
.globl gallery_list_draw
gallery_list_draw:
    lw      $t0,0x24($a0)
    lui     $t1,%hi(gallery_selector)
    addiu   $t1,$t1,%lo(gallery_selector)
    bne     $t0,$t1,list_draw_original
    nop
    /* Only the gallery list: twelve rows at a twelve-unit pitch. Keep the
     * stock font size, frame and input controller, with one page. The native
     * slide tween causes fractional-position text sampling; draw at rest.
     */
    sw      $zero,0x68($a0)
    sw      $zero,0x6c($a0)
    lui     $t0,0x0076
    lw      $t0,0x3a50($t0)
    beq     $t0,$zero,list_draw_original
    nop
    addiu   $t1,$zero,12
    sh      $t1,6($t0)
    sh      $t1,8($t0)
    sb      $t1,0x0d($t0) /* input controller's selectable row count */
    sw      $t1,0x18($t0)
    addiu   $t1,$zero,144
    sh      $t1,10($t0)
    addiu   $t1,$zero,1
    sb      $t1,0x13($t0)
    sb      $zero,0x12($t0)
list_draw_original:
    /* Original 320f30 prologue, then its untouched body. */
    addiu   $sp,$sp,-0x30
    sd      $ra,0x20($sp)
    j       0x00320f38
    nop

.org 0x700
.globl gallery_draw_caption
gallery_draw_caption:
    addiu   $sp,$sp,-0x30
    sd      $ra,0x28($sp)
    sd      $s0,0x20($sp)
    sd      $s1,0x18($sp)
    sd      $s2,0x10($sp)
    daddu   $s0,$a0,$zero
    lui     $s1,0x0063
    addiu   $s1,$s1,-0x6450 /* 629bb0 effect pool */
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
    lui     $s2,0x0082
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
    /* Save this field's clean display, keyed by its native framebuffer. */
    lw      $t0,0($s2)
    addiu   $t1,$zero,257
    bne     $t0,$t1,caption_history_saved
    nop
    lui     $t0,0x004d
    lbu     $t0,-0x4f80($t0) /* 004cb080 late screen pass enabled */
    beq     $t0,$zero,caption_history_saved
    nop
    daddu   $a0,$s0,$zero
    lui     $t0,0x0045
    lw      $t0,0x7cf0($t0)
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
    lui     $t0,0x0082
    lw      $t2,0x1f10($t0)
    or      $t2,$t2,$t1
    sw      $t2,0x1f10($t0)
    jal     gallery_copy_caption_rect
    daddu   $a3,$zero,$zero
    daddu   $s0,$v0,$zero
caption_history_saved:
    lui     $t0,0x0082
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
    lui     $s1,0x0082
    ori     $s1,$s1,0x1d00
    lui     $t0,0x0082
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
    lui     $t0,0x0082
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
    jal     0x001b0f30       /* final overlay, outside the scene's post effects */
    daddu   $a3,$zero,$zero
    /* The native sprite path writes TEX1_1 = 0 (nearest). Filter the caption
       bilinearly: the 2-rows-per-native-row atlas then averages at native
       resolution and magnifies smoothly in upscaled renderers. */
    addiu   $t0,$s0,48
    addiu   $t3,$zero,16
gallery_tex1_scan:
    ld      $t1,8($t0)
    addiu   $t2,$zero,0x14  /* A+D register TEX1_1 */
    bne     $t1,$t2,gallery_tex1_next
    nop
    ld      $t1,0($t0)
    ori     $t1,$t1,0x60    /* MMAG = MMIN = LINEAR */
    b       gallery_tex1_done
    sd      $t1,0($t0)
gallery_tex1_next:
    addiu   $t3,$t3,-1
    bne     $t3,$zero,gallery_tex1_scan
    addiu   $t0,$t0,16
gallery_tex1_done:
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
.globl gallery_final_draw
gallery_final_draw:
    addiu   $sp,$sp,-0x30
    sd      $ra,0x28($sp)
    sd      $s0,0x20($sp)
    jal     0x00141810       /* original poll after late screen/post-effect passes */
    nop
    jal     gallery_finish_feedback
    nop
    lui     $t0,0x0082
    lw      $t0,0x1f04($t0)
    addiu   $t1,$zero,2
    bne     $t0,$t1,final_draw_return
    nop
    lui     $s0,%hi(GALLERY_PACKET)
    addiu   $s0,$s0,%lo(GALLERY_PACKET) /* private GIF packet buffer */
    jal     gallery_draw_caption
    daddu   $a0,$s0,$zero
    subu    $s0,$v0,$s0
    beq     $s0,$zero,final_draw_return
    nop
    jal     0x0011b260       /* FlushCache(0), before the final direct GIF DMA */
    daddu   $a0,$zero,$zero
    lui     $t0,0x1001
    lui     $t1,%hi(GALLERY_PACKET)
    addiu   $t1,$t1,%lo(GALLERY_PACKET)
    sw      $t1,-0x5ff0($t0) /* GIF MADR */
    srl     $s0,$s0,4
    sw      $s0,-0x5fe0($t0) /* GIF QWC */
    addiu   $t1,$zero,0x101
    sw      $t1,-0x6000($t0) /* GIF CHCR, normal transfer */
    jal     0x0016b558       /* finish overlay before the frame is presented */
    nop
final_draw_return:
    ld      $s0,0x20($sp)
    ld      $ra,0x28($sp)
    jr      $ra
    addiu   $sp,$sp,0x30

.org 0xc00
gallery_copy_caption_rect:
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
gallery_submit_copy:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    lui     $a0,%hi(GALLERY_PACKET)
    addiu   $a0,$a0,%lo(GALLERY_PACKET)
    jal     gallery_copy_caption_rect
    nop
    jal     0x0011b260
    daddu   $a0,$zero,$zero
    lui     $t0,0x1001
    lui     $t1,%hi(GALLERY_PACKET)
    addiu   $t1,$t1,%lo(GALLERY_PACKET)
    sw      $t1,-0x5ff0($t0)
    addiu   $t1,$zero,6
    sw      $t1,-0x5fe0($t0)
    addiu   $t1,$zero,0x101
    sw      $t1,-0x6000($t0)
    jal     0x0016b558
    nop
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20

.org 0xe00
gallery_prepare_feedback:
    addiu   $sp,$sp,-0x40
    sd      $ra,0x38($sp)
    sd      $s0,0x30($sp)
    sd      $s1,0x28($sp)
    sd      $s2,0x20($sp)
    jal     0x0016de40
    nop
    daddu   $s0,$v0,$zero
    lui     $t0,0x0082
    lw      $t1,0x1f04($t0)
    ori     $t2,$zero,2
    bne     $t1,$t2,prepare_feedback_return
    nop
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
    jal     gallery_submit_copy
    daddu   $a3,$zero,$zero
    daddu   $a1,$s2,$zero
    daddu   $a2,$s1,$zero
    jal     gallery_submit_copy
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
gallery_finish_feedback:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    lui     $t0,0x0082
    lw      $t1,0x1f18($t0)
    beq     $t1,$zero,finish_feedback_mask
    nop
    sw      $zero,0x1f18($t0)
    ori     $a1,$zero,0x3f00
    lw      $a2,0x1f14($t0)
    jal     gallery_submit_copy
    ori     $a3,$zero,1
finish_feedback_mask:
    lui     $t0,0x0045
    lw      $t0,0x7cf0($t0)
    andi    $t0,$t0,1
    ori     $t1,$zero,1
    sllv    $t1,$t1,$t0
    nor     $t1,$t1,$zero
    lui     $t0,0x0082
    lw      $t2,0x1f10($t0)
    and     $t2,$t2,$t1
    sw      $t2,0x1f10($t0)
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20

.org 0x1300
gallery_clear_transition:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    jal     0x0016b558       /* retire the previous theater GIF transfer */
    nop
    jal     0x0011b260
    daddu   $a0,$zero,$zero
    lui     $t0,0x1001
    lui     $t1,%hi(gallery_transition_packet)
    addiu   $t1,$t1,%lo(gallery_transition_packet)
    sw      $t1,-0x5ff0($t0)
    addiu   $t1,$zero,15
    sw      $t1,-0x5fe0($t0)
    addiu   $t1,$zero,0x101
    sw      $t1,-0x6000($t0)
    jal     0x0016b558
    nop
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20

.org 0x1400
gallery_initialize_stage_objects:
    sll     $a0,$a0,2
    lui     $t0,%hi(gallery_stage_objects)
    addiu   $t0,$t0,%lo(gallery_stage_objects)
    addu    $t0,$t0,$a0
    lw      $t0,0($t0)
    bne     $t0,$zero,initialize_objects
    nop
    jr      $ra
    nop
initialize_objects:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    sd      $s0,0x10($sp)
    daddu   $s0,$t0,$zero
initialize_object_next:
    lw      $a0,0($s0)
    bltz    $a0,initialize_objects_done
    nop
    lw      $a1,4($s0)
    jal     0x00147510
    lw      $a2,8($s0)
    lw      $a0,0($s0)
    jal     0x00147490
    lw      $a1,12($s0)
    b       initialize_object_next
    addiu   $s0,$s0,16
initialize_objects_done:
    ld      $s0,0x10($sp)
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20

.org 0x1500
.align 4
gallery_transition_packet:
    /* The 640x224 PSMCT32 fill covers the same bytes as the theater's
     * 640x448 PSMCT16 frame. Both FBP 0 and 0x46 must be cleared. */
    .dword 0x100000000000800e, 0x000000000000000e
    .dword 0x00000000000a0000, 0x4c /* FRAME_1: FBP 0, FBW 10, PSMCT32 */
    .dword 0x0000000100000000, 0x4e /* ZBUF_1: writes masked */
    .dword 0, 0x18                 /* XYOFFSET_1 */
    .dword 0x00df0000027f0000, 0x40 /* SCISSOR_1 */
    .dword 0, 0x47                 /* TEST_1 */
    .dword 0, 0x22                 /* SCANMSK */
    .dword 0, 0x45                 /* DTHE */
    .dword 6, 0                    /* PRIM: untextured sprite, no blending */
    .dword 0x80000000, 1           /* RGBAQ: opaque black */
    .dword 0, 5
    .dword 0x0e002800, 5
    .dword 0x00000000000a0046, 0x4c /* FRAME_1: other display buffer */
    .dword 0, 5
    .dword 0x0e002800, 5

.org 0x1800
gallery_save_roster:
    lui     $t0,0x005a
    ori     $t0,$t0,0x5080
    lui     $t1,0x0083
    lui     $t2,0x0007
    ori     $t2,$t2,0x6940
save_roster_loop:
    ld      $t3,0($t0)
    sd      $t3,0($t1)
    addiu   $t0,$t0,8
    addiu   $t1,$t1,8
    addiu   $t2,$t2,-8
    bne     $t2,$zero,save_roster_loop
    nop
    lui     $t0,0x0076
    ori     $t0,$t0,0x1500
    addiu   $t2,$zero,256
save_spawn_results:
    ld      $t3,0($t0)
    sd      $t3,0($t1)
    addiu   $t0,$t0,8
    addiu   $t1,$t1,8
    addiu   $t2,$t2,-8
    bne     $t2,$zero,save_spawn_results
    nop
    /* Stage flags, camera zoom and placeholder-actor state follow. */
    lui     $t4,%hi(gallery_state_regions)
    addiu   $t4,$t4,%lo(gallery_state_regions)
save_region:
    lw      $t0,0($t4)
    beq     $t0,$zero,save_regions_done
    lw      $t2,4($t4)
save_region_word:
    lw      $t3,0($t0)
    sw      $t3,0($t1)
    addiu   $t0,$t0,4
    addiu   $t1,$t1,4
    addiu   $t2,$t2,-4
    bne     $t2,$zero,save_region_word
    nop
    b       save_region
    addiu   $t4,$t4,8
save_regions_done:
    jr      $ra
    nop

gallery_restore_roster:
    lui     $t0,0x0083
    lui     $t1,0x005a
    ori     $t1,$t1,0x5080
    lui     $t2,0x0007
    ori     $t2,$t2,0x6940
restore_roster_loop:
    ld      $t3,0($t0)
    sd      $t3,0($t1)
    addiu   $t0,$t0,8
    addiu   $t1,$t1,8
    addiu   $t2,$t2,-8
    bne     $t2,$zero,restore_roster_loop
    nop
    lui     $t1,0x0076
    ori     $t1,$t1,0x1500
    addiu   $t2,$zero,256
restore_spawn_results:
    ld      $t3,0($t0)
    sd      $t3,0($t1)
    addiu   $t0,$t0,8
    addiu   $t1,$t1,8
    addiu   $t2,$t2,-8
    bne     $t2,$zero,restore_spawn_results
    nop
    lui     $t4,%hi(gallery_state_regions)
    addiu   $t4,$t4,%lo(gallery_state_regions)
restore_region:
    lw      $t1,0($t4)
    beq     $t1,$zero,restore_regions_done
    lw      $t2,4($t4)
restore_region_word:
    lw      $t3,0($t0)
    sw      $t3,0($t1)
    addiu   $t0,$t0,4
    addiu   $t1,$t1,4
    addiu   $t2,$t2,-4
    bne     $t2,$zero,restore_region_word
    nop
    b       restore_region
    addiu   $t4,$t4,8
restore_regions_done:
    jr      $ra
    nop

.align 4
gallery_state_regions:
    .word 0x005dbc40,0x80    /* stage flag bitset (placeholder actors) */
    .word 0x00457748,4       /* map camera zoom */
    .word 0x0062da18,8       /* placeholder slot groups and table */
    .word 0x0061e180,4       /* placeholder draw callback */
    .word 0x0061bfc0,0xa00   /* map-sprite cache entries */
    .word 0x0062a830,0x230   /* resident/dynamic map-effect table and block pointers */
    .word 0,0

.align 4
gallery_bgm_restore:
    addiu   $sp,$sp,-0x20
    sd      $ra,0x18($sp)
    lui     $t0,0x0062
    lw      $t1,0x890($t0)   /* 00620890 sound request state */
    bne     $t1,$zero,bgm_restore_wait
    nop
    lui     $t0,0x0082
    sw      $zero,0x1f24($t0)
    lw      $a0,0x1f20($t0)
    lui     $t1,0x005e
    lbu     $t1,-0x4468($t1)
    beq     $t1,$a0,bgm_restore_wait
    nop
    daddu   $a1,$zero,$zero
    daddu   $a2,$zero,$zero
    addiu   $a3,$zero,1
    addiu   $t0,$zero,3
    jal     0x00182fc0       /* native load/play, as script op 0x43 */
    daddu   $t1,$zero,$zero
bgm_restore_wait:
    ld      $ra,0x18($sp)
    jr      $ra
    addiu   $sp,$sp,0x20

.align 4
gallery_bgm_pause:
    /* Effect-header BGM scenes: pause the theater track (sound state 5,
     * request 2) so the resource's own BGM starts without the menu tune. */
    j       0x00183220
    addiu   $a0,$zero,2


.org 0x1a00
.globl gallery_prepare_units
gallery_prepare_units:
    /* a0: (SP unit id, SP pilot id) halfword pairs, 0xffff terminated.
     * Stage roster construction normally provides these objects. Use an
     * existing native template or initialize a placeholder slot with the
     * native definition loaders; the complete roster snapshot is restored. */
    addiu   $sp,$sp,-0x40
    sd      $ra,0x38($sp)
    sd      $s0,0x30($sp)
    sd      $s1,0x28($sp)
    sd      $s2,0x20($sp)
    sd      $s3,0x18($sp)
    daddu   $s0,$a0,$zero
prepare_next:
    lhu     $s3,0($s0)
    ori     $t0,$zero,0xffff
    beq     $s3,$t0,prepare_done
    nop
    lui     $s1,0x005c
    addiu   $s1,$s1,-0x6b00  /* 005b9500 unit objects */
    daddu   $s2,$zero,$zero
    addiu   $t0,$zero,502
    lui     $t6,0x007c
    ori     $t6,$t6,0x7da4   /* placeholder unit definition */
find_unit:
    lw      $t1,0xa8($s1)
    beq     $t1,$t6,unit_placeholder
    nop
    beq     $t1,$zero,unit_next
    nop
    lhu     $t2,0($t1)
    beq     $t2,$s3,unit_ready
    nop
    b       unit_next
    nop
unit_placeholder:
    bne     $s2,$zero,unit_next
    nop
    daddu   $s2,$s1,$zero
unit_next:
    addiu   $s1,$s1,0x118
    addiu   $t0,$t0,-1
    bne     $t0,$zero,find_unit
    nop
    beq     $s2,$zero,prepare_skip
    nop
    lui     $t1,0x005c
    addiu   $t1,$t1,-0x6b00
    subu    $a0,$s2,$t1
    addiu   $t2,$zero,0x118
    divu    $zero,$a0,$t2
    mflo    $a0
    daddu   $a1,$s3,$zero
    jal     0x00149710       /* native unit object from definition */
    daddu   $a2,$zero,$zero
    daddu   $s1,$s2,$zero
unit_ready:
    sw      $s1,0x10($sp)
    lhu     $s3,2($s0)
    lui     $s1,0x005a
    ori     $s1,$s1,0x5080   /* 005a5080 pilot objects */
    daddu   $s2,$zero,$zero
    addiu   $t0,$zero,472
    lui     $t6,0x0079
    ori     $t6,$t6,0x1c92   /* placeholder pilot definition */
find_pilot:
    lw      $t1,0($s1)
    beq     $t1,$t6,pilot_placeholder
    nop
    beq     $t1,$zero,pilot_next
    nop
    lhu     $t2,0($t1)
    beq     $t2,$s3,pilot_ready
    nop
    b       pilot_next
    nop
pilot_placeholder:
    bne     $s2,$zero,pilot_next
    nop
    daddu   $s2,$s1,$zero
pilot_next:
    addiu   $s1,$s1,0xb0
    addiu   $t0,$t0,-1
    bne     $t0,$zero,find_pilot
    nop
    beq     $s2,$zero,prepare_skip
    nop
    lui     $t1,0x005a
    ori     $t1,$t1,0x5080
    subu    $a0,$s2,$t1
    addiu   $t2,$zero,0xb0
    divu    $zero,$a0,$t2
    mflo    $a0
    daddu   $a1,$s3,$zero
    jal     0x001492c0       /* native pilot object from definition */
    daddu   $a2,$zero,$zero
    daddu   $s1,$s2,$zero
pilot_ready:
    lw      $s2,0x10($sp)
    lbu     $t0,0xc9($s2)
    ori     $t0,$t0,1
    sb      $t0,0xc9($s2)
    lbu     $t0,0x3e($s1)
    ori     $t0,$t0,1
    sb      $t0,0x3e($s1)
    daddu   $a0,$s2,$zero
    daddu   $a1,$s1,$zero
    jal     0x00288140       /* native attachment, within saved roster */
    addiu   $a2,$zero,1
    lbu     $t0,0xca($s2)
    ori     $t0,$t0,2
    sb      $t0,0xca($s2)
    daddu   $a0,$s2,$zero
    jal     0x00174a80       /* native map-sprite cache entry for the definition */
    daddu   $a1,$zero,$zero
prepare_skip:
    b       prepare_next
    addiu   $s0,$s0,4
prepare_done:
    ld      $s3,0x18($sp)
    ld      $s2,0x20($sp)
    ld      $s1,0x28($sp)
    ld      $s0,0x30($sp)
    ld      $ra,0x38($sp)
    daddu   $v0,$zero,$zero
    jr      $ra
    addiu   $sp,$sp,0x40

.include "gallery-scenes.inc"
