/* Native SP event gallery, SLPS_259.20 only.
 * Link .text at 0x00822000 and copy gallery_runtime.bin there.
 * Replace only JAL at 0x00143ea8 with JAL gallery_frame (0x00822100).
 * Existing menu selector callback is 0x00822000.
 * State at 0x00821f00: +0 selected row, +4 phase (0 list, 1 requested,
 * 2 playing, 3 completed), +8 last completed row, +0x10 feedback valid mask,
 * +0x14 temporary source framebuffer, +0x18 pending restoration,
 * +0x20 theater BGM id, +0x24 theater BGM restore pending,
 * +0x28 placeholder-actor table before playback, +0x30 resident map effects
 * loaded for this theater session, +0x34 frames played (cancel guard),
 * +0x38 previous pad held mask, +0x40 saved unit flags (120 bytes),
 * +0xc0 dialogue auto-play record (native auto level 2),
 * +0xcc last frame spent in map dialogue (cancel guard), +0xd0 play mode
 * (1 with dialogue), +0xd4 triangle pending, +0xd8 gallery list on screen.
 * Playback can be cancelled with cross or START: a new press seen
 * on the pad held mask (0062514c; the frozen list widget consumes the
 * native trigger word for cross/circle) runs the completion path at once.
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
    /* Play mode +0xd0: 1 = with map dialogue (entered with triangle, which
     * gallery_list_input turned into this confirm), 0 = effects only. */
    lw      $v0,0x1fd4($v1)
    sltu    $v0,$zero,$v0
    sw      $v0,0x1fd0($v1)
    sw      $zero,0x1fd4($v1)
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
    sw      $zero,0x1be0($t0)
    sw      $zero,0x1be4($t0)
    lw      $t1,0x1f04($t0)
    bne     $t1,$zero,frame_active
    nop
frame_native:
    /* Triangle on the gallery list enters the scene with dialogue. */
    daddu   $t9,$ra,$zero
    jal     gallery_list_input
    nop
    daddu   $ra,$t9,$zero
    lui     $t0,0x0082
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
    sw      $zero,0x34($s1)
    sw      $zero,0xc0($s1)
    sw      $zero,0xcc($s1)
    jal     gallery_talk_mode
    nop
    addiu   $t2,$zero,0xffff
    sw      $t2,0x38($s1)    /* no cancel edge until every button is released */
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
    jal     gallery_cancel_check
    nop
    beq     $v0,$zero,cancel_checked
    nop
    addiu   $t0,$zero,3
    sw      $t0,4($s1)
    b       frame_complete
    nop
cancel_checked:
    jal     gallery_talk_auto
    nop
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
    lui     $t2,0x004d
    lbu     $t2,-0x518c($t2) /* 004cae74 clear colour: 0xff in a script blank */
    bne     $t2,$zero,map_draw_set /* op 0x13ac 2 turned map and unit drawing off */
    nop
    sw      $t1,0x45a0($t0)
map_draw_set:
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
    /* Release the map-dialogue player a scene with dialogue created. */
    lui     $t0,0x0063
    lw      $t1,-0x1c80($t0)  /* 0062e380 dialogue player */
    beq     $t1,$zero,talk_released
    nop
    jal     0x002048c0       /* native dialogue teardown (clears 0062e380) */
    nop
talk_released:
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
    /* Only mark the gallery list as on screen for triangle input.
     * Keep native +0x68/+0x6c slide offsets: clearing them here resets the
     * exit tween every frame, leaving the panel stuck until it vanishes.
     * The native offsets already settle at zero while the list is idle. */
    lui     $t0,0x0082
    addiu   $t1,$zero,2
    sw      $t1,0x1fd8($t0)
list_draw_original:
    /* Original 320f30 prologue, then its untouched body. */
    addiu   $sp,$sp,-0x30
    sd      $ra,0x20($sp)
    j       0x00320f38
    nop

/* Enlarge height-8 menu glyphs (digits and Showtime t) to 8.5 native units.
 * Their aligned
 * bottom vertex stays fixed; the top moves up half a native Y unit.
 * Other Showtime letters keep height 9; widths and advances are in the menu.
 */
.org 0x580
.globl gallery_list_digit_height
gallery_list_digit_height:
    or      $t1,$t4,$t1      /* displaced bottom-right XYZ composition */
    lui     $at,0x0082
    lw      $t3,0x1be0($at)
    sltu    $at,$a3,$t3
    bne     $at,$zero,list_digit_height_done
    lui     $at,0x0082
    lw      $t3,0x1be4($at)
    sltu    $at,$a3,$t3
    beq     $at,$zero,list_digit_height_done
    lhu     $t3,0x0e($a3)
    addiu   $t3,$t3,-8
    bne     $t3,$zero,list_digit_height_done
    lui     $at,0x0008
    dsubu   $t5,$t5,$at
list_digit_height_done:
    j       0x0013bda8
    addiu   $t3,$t0,23      /* displaced UV computation */

/* Reserve font slot 113 (w), checked blank/unassigned by the builder.
 * Native upload requests hold glyph_index*288 in T1. Only w sources a
 * private raster; every other upload keeps the original font pointer.
 */
.org 0x5d0
.globl gallery_w_upload
gallery_w_upload:
    j       gallery_private_upload
    nop

/* Before native packet generation: correct only glyphs sourced from the
 * gallery menu pool. S4 is the pointer just after the current encoded glyph.
 * V0/V1 are dead here; restore AT and replay both displaced instructions.
 */
.org 0x600
.globl gallery_list_glyph
gallery_list_glyph:
    lui     $at,0x0082
    subu    $v0,$s4,$at
    sltiu   $v0,$v0,0x1be0
    beq     $v0,$zero,list_glyph_clear
    nop
    lw      $v0,0x1be0($at)
    bne     $v0,$zero,list_glyph_end
    nop
    sw      $s0,0x1be0($at)
list_glyph_end:
    addiu   $v0,$s0,0x20
    b       list_glyph_digit
    sw      $v0,0x1be4($at)
list_glyph_clear:
    sw      $zero,0x1be0($at)
    sw      $zero,0x1be4($at)
list_glyph_digit:
    lui     $v0,0x0082
    subu    $v0,$s4,$v0
    sltiu   $v0,$v0,0x1be0
    beq     $v0,$zero,list_glyph_done
    lhu     $v0,0x0e($s0)
    addiu   $v0,$v0,-8
    bne     $v0,$zero,list_glyph_done
    lh      $v0,0x06($s0)
    addiu   $v0,$v0,1
    sh      $v0,0x06($s0)
list_glyph_done:
    lui     $at,0x7000
    lbu     $v1,0x4a($s1)
    j       0x0013b5f8
    sb      $v1,0x12($s0)

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
    /* +0x3f effect state: 2 loading, 3 loaded, 1 playing. A loading entry
     * already carries its id at frame 0; drawing then shows a black band. */
    lbu     $t0,0x3f($s1)
    addiu   $t3,$zero,1
    bne     $t0,$t3,caption_next_effect
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

/* Returning from the gallery: reuse the root page's native staggered
 * rotation scheduler, including its hidden-item filtering and 10-frame steps.
 * S5=root page and S1=native animation queue in the native 322290 epilogue.
 */
.org 0xb00
.globl gallery_root_return
gallery_root_return:
    beq     $s1,$zero,root_return_done
    nop
    lw      $t0,0($s5)
    bne     $t0,$zero,root_return_done
    nop
    lw      $t0,0x20c($s5)
    beq     $t0,$zero,root_return_done
    nop
    lw      $t0,0($t0)
    addiu   $t0,$t0,-9
    bne     $t0,$zero,root_return_done
    nop
    /* Start after native slide completion; both animations share each
     * widget controller, so starting earlier cancels the first slide. */
    daddu   $a0,$s5,$zero
    daddu   $a1,$v0,$zero
    jal     0x003236e0
    daddu   $a2,$s1,$zero
    /* Return the extended completion time to the native input scheduler. */
root_return_done:
    ld      $ra,0x70($sp)
    .word   0x7bb60060      /* lq s6,0x60(sp), EE instruction */
    j       0x00322b20
    nop

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
    lui     $t1,0x0084       /* snapshot base 0x846000 (dialogue blocks below) */
    ori     $t1,$t1,0x6000
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
    lui     $t0,0x0084       /* snapshot base 0x846000 */
    ori     $t0,$t0,0x6000
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
    .word 0x00457784,4       /* map rotation: an effect cancelled mid-turn leaves it set */
    .word 0x0062da18,8       /* placeholder slot groups and table */
    .word 0x0061e180,4       /* placeholder draw callback */
    .word 0x0061bfc0,0xa00   /* map-sprite cache entries */
    .word 0x0062a830,0x230   /* resident/dynamic map-effect table and block pointers */
    .word 0x005a3e00,0x1280  /* screen-layer table and effect quads up to the roster
                              * snapshot: an effect cancelled mid-way (257 feedback
                              * layers) must not leave its distortion layers on */
    .word 0x00629b60,0xa0    /* shared CCC voice timeline and its playback cursor */
    .word 0x0061e1e0,4       /* map-dialogue block pointer (scenes install their own) */
    .word 0x0061e1a8,4       /* speaker cursor table (scenes install their own) */
    .word 0x004caab0,4       /* game mode: map dialogue switches it to 0x13 */
    .word 0x004cb080,4       /* late screen pass enable: an effect cancelled mid-way
                              * (257) leaves it on and the list draws with trails */
    .word 0,0




.org 0x1a00
.globl gallery_prepare_units
gallery_prepare_units:
    /* a0: (SP unit id, SP pilot id) halfword pairs, 0xffff terminated.
     * Stage roster construction normally provides these objects. Use an
     * existing native template or initialize a placeholder slot with the
     * native definition loaders; the complete roster snapshot is restored.
     * Unit id 0xfffe seats the pilot in the previous unit's next free seat
     * (a sub-pilot: the native speaker lookup checks all six seats). */
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
    ori     $t0,$zero,0xfffe
    /* crew_pilot follows the scene data, out of conditional-branch range */
    bne     $s3,$t0,prepare_unit
    addiu   $t0,$zero,1
    j       crew_pilot
    nop
prepare_unit:
    sw      $zero,0x14($sp)  /* not a sub-pilot */
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
pilot_lookup:
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
    lw      $t0,0x14($sp)
    beq     $t0,$zero,pilot_not_crew
    nop
    j       crew_board       /* past the scene data, out of branch range */
    nop
pilot_not_crew:
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

.text
.align 4
/* gallery_prepare_units, sub-pilot path (out of its 0x1a00 block) */
crew_pilot:
    b       pilot_lookup
    sw      $t0,0x14($sp)
crew_board:
    lbu     $t0,0x3e($s1)
    ori     $t0,$t0,1
    sb      $t0,0x3e($s1)
    addiu   $t1,$s2,0xb4     /* seats 1..5 */
    addiu   $t2,$zero,5
seat_next:
    lw      $t3,0($t1)
    beq     $t3,$zero,seat_put
    addiu   $t2,$t2,-1
    bne     $t2,$zero,seat_next
    addiu   $t1,$t1,4
    b       prepare_skip
    nop
seat_put:
    b       prepare_skip
    sw      $s1,0($t1)

.align 4
.globl gallery_cancel_check
/* Returns v0 = 1 after cancelling (sounds stopped, blank undone), else 0. */
gallery_cancel_check:
    addiu   $sp,$sp,-0x10
    sd      $ra,0($sp)
    /* Cancel: a new press of cross or START after the first 20 frames
     * (the list's own confirm press must not count) ends the scene now. */
    lw      $t1,0x34($s1)
    addiu   $t1,$t1,1
    sw      $t1,0x34($s1)
    sltiu   $t2,$t1,20
    bne     $t2,$zero,cancel_none
    nop
    lui     $t0,0x0062
    lhu     $t0,0x514c($t0)  /* 0062514c pad held mask */
    lw      $t1,0x38($s1)
    sw      $t0,0x38($s1)
    nor     $t1,$t1,$zero    /* buttons not held last frame */
    and     $t0,$t0,$t1
    /* Circle pages the dialogue window and never cancels. During map dialogue
     * (script op 0x0f) and for 60 frames after it, only START cancels, so an
     * extra page press after the last line does not end the scene. Raw pad
     * order: cross 0x0040, START 0x0800. +0xcc = last frame inside dialogue. */
    lui     $t2,0x0062
    lh      $t2,-0x2150($t2) /* 0061deb0 script opcode */
    addiu   $t3,$zero,0x0f
    bne     $t2,$t3,cancel_after_talk
    lw      $t4,0x34($s1)
    sw      $t4,0xcc($s1)
    b       cancel_mask_done
    andi    $t1,$t0,0x0800
cancel_after_talk:
    lw      $t5,0xcc($s1)
    subu    $t5,$t4,$t5
    sltiu   $t5,$t5,60
    bne     $t5,$zero,cancel_mask_done
    andi    $t1,$t0,0x0800
    andi    $t1,$t0,0x0840
cancel_mask_done:
    beq     $t1,$zero,cancel_none
    nop
    /* Consume this press: the list widget resumes this frame and would take
     * the same cross as "back" (the trigger copies at 0062514e/52/54/56). */
    lui     $t0,0x0062
    sh      $zero,0x514e($t0)
    sh      $zero,0x5152($t0)
    sh      $zero,0x5154($t0)
    sh      $zero,0x5156($t0)
    /* Undo a script blank (op 0x13ac 2: clear colour 0xff, map layers off)
     * that the interrupted script would have reverted itself. */
    lui     $t0,0x004d
    sb      $zero,-0x518c($t0) /* 004cae74 clear colour r (gp-0x79fc) */
    sb      $zero,-0x5188($t0) /* 004cae78 g (gp-0x79f8) */
    sb      $zero,-0x5184($t0) /* 004cae7c b (gp-0x79f4) */
    daddu   $a0,$zero,$zero
    jal     0x001c21b0       /* map layers back on (op 0x13ac 0) */
    addiu   $a1,$zero,1
    /* A cancelled line would otherwise stream to its end: stop both CCC
     * voice stream channels and the effect sound-effect channels. BGM is
     * left alone; the theater BGM restore follows. */
    jal     0x00183bb0       /* stop voice stream channels (uGpffff80ec, +1) */
    nop
    jal     0x00183b70       /* stop the 0x30 sound-effect channels */
    nop
    b       cancel_return
    addiu   $v0,$zero,1
cancel_none:
    daddu   $v0,$zero,$zero
cancel_return:
    ld      $ra,0($sp)
    jr      $ra
    addiu   $sp,$sp,0x10

.align 4
.globl gallery_talk_auto
gallery_talk_auto:
    /* Auto-play map dialogue with the native auto mode at level 2. The native
     * auto timer (*0062e598) pages after +0x10[level] frames: 240/180/120/60
     * for levels 1-4; the gallery switches the controller (*0062e588 +4) and
     * timer (+4 on, +8 level 2) on and restarts the timer count (+0xc) on each
     * new record. Leave paging to the native window; synthetic circle presses
     * would bypass the setting while text or voice is still playing.
     * State +0xc0 holds the current record. */
    lui     $t0,0x0062
    lh      $t1,-0x2150($t0) /* 0061deb0 script opcode */
    addiu   $t2,$zero,0x0f
    bne     $t1,$t2,talk_auto_done
    lui     $t0,0x0063
    lw      $t1,-0x1c80($t0) /* 0062e380 dialogue player */
    beq     $t1,$zero,talk_auto_done
    nop
    lw      $t2,0x0c($t1)    /* current dialogue record */
    lw      $t5,-0x1a78($t0) /* 0062e588 native auto controller */
    lw      $t6,-0x1a68($t0) /* 0062e598 native auto timer */
    addiu   $t7,$zero,1
    beq     $t5,$zero,talk_auto_timer
    nop
    sb      $t7,4($t5)
talk_auto_timer:
    beq     $t6,$zero,talk_auto_record
    nop
    sb      $t7,4($t6)
    addiu   $t7,$zero,2
    sw      $t7,8($t6)       /* level 2: 180 frames a page */
talk_auto_record:
    lw      $t3,0xc0($s1)
    beq     $t2,$t3,talk_auto_done
    nop
    sw      $t2,0xc0($s1)
    beq     $t6,$zero,talk_auto_done
    nop
    sw      $zero,0x0c($t6)  /* restart the native page count */
talk_auto_done:
    jr      $ra
    nop

.align 4
gallery_list_input:
    /* On the gallery list, triangle = play with map dialogue: remember the
     * request (+0xd4, valid this frame and the next) and hand the native list
     * a circle so it confirms the row under the cursor as usual. Uses t0-t4. */
    lui     $t0,0x0082
    lw      $t1,0x1fd4($t0)
    beq     $t1,$zero,list_input_seen
    addiu   $t1,$t1,-1
    sw      $t1,0x1fd4($t0)
list_input_seen:
    lw      $t1,0x1fd8($t0)
    beq     $t1,$zero,list_input_done
    addiu   $t1,$t1,-1
    sw      $t1,0x1fd8($t0)
    lui     $t2,0x0062
    lhu     $t3,0x514e($t2)  /* 0062514e trigger copy, raw order */
    andi    $t4,$t3,0x0010   /* triangle */
    beq     $t4,$zero,list_input_done
    addiu   $t4,$zero,2
    sw      $t4,0x1fd4($t0)
    addiu   $t3,$zero,0x0020 /* circle */
    sh      $t3,0x514e($t2)
    sh      $t3,0x5152($t2)
    sh      $t3,0x5154($t2)
    sh      $t3,0x5156($t2)
list_input_done:
    jr      $ra
    nop

.align 4
gallery_talk_mode:
    /* Scene start: triangle (+0xd0 != 0) restores op 0x0f n of every map-dialogue
     * op; circle (effects only) turns it into "0x52 gallery_quiet_sub, pilots",
     * which moves the cursor and camera as the section's speakers would. The
     * mode words after the table's terminator are set for the chosen mode. */
    lw      $t0,0($s1)
    sll     $t0,$t0,2
    lui     $t1,%hi(gallery_talkop_tables)
    addiu   $t1,$t1,%lo(gallery_talkop_tables)
    addu    $t1,$t1,$t0
    lw      $t1,0($t1)
    beq     $t1,$zero,talk_mode_done
    lw      $t2,0xd0($s1)
talk_mode_next:
    lw      $t3,0($t1)       /* record address */
    beq     $t3,$zero,mode_word_next
    lw      $t4,4($t1)       /* section | cursor << 16 */
    beq     $t2,$zero,talk_mode_quiet
    andi    $t5,$t4,0xffff
    addiu   $t6,$zero,0x0f
    sw      $t6,0($t3)
    sw      $t5,4($t3)
    sw      $zero,8($t3)
    srl     $t5,$t4,16
    b       talk_mode_step
    sw      $t5,12($t3)
talk_mode_quiet:
    addiu   $t6,$zero,0x52   /* gosub gallery_quiet_sub */
    sw      $t6,0($t3)
    lui     $t6,%hi(gallery_quiet_sub)
    addiu   $t6,$t6,%lo(gallery_quiet_sub)
    sw      $t6,4($t3)
    lw      $t6,8($t1)       /* the section's speaking pilots */
    sw      $t6,8($t3)
    sw      $zero,12($t3)    /* next line */
talk_mode_step:
    b       talk_mode_next
    addiu   $t1,$t1,12
mode_word_next:
    /* After the talk ops: (word address, triangle value, circle value) per
     * mode-dependent word, e.g. a wait that circle mode shortens; 0-terminated. */
    addiu   $t1,$t1,12
    lw      $t3,0($t1)
    beq     $t3,$zero,talk_mode_done
    lw      $t4,4($t1)
    bne     $t2,$zero,mode_word_store
    nop
    lw      $t4,8($t1)
mode_word_store:
    b       mode_word_next
    sw      $t4,0($t3)
talk_mode_done:
    jr      $ra
    nop

.align 4
gallery_skip:
    /* Record "0x14 gallery_skip, 0, target": the script continues at target.
     * Circle mode (effects only) lays it over the first record of a part only the
     * dialogue version plays (mode words, gallery_talk_mode), so triangle keeps
     * its records and timing. */
    lui     $t0,0x0062
    lw      $t1,-0x2148($t0) /* 0061deb8 current record */
    lw      $t1,12($t1)
    addiu   $t1,$t1,-16
    jr      $ra
    sw      $t1,-0x2148($t0) /* the interpreter advances onto the target */

.align 4
gallery_bgm_pause:
    /* Effect-header BGM scenes: pause the theater track (sound state 5,
     * request 2) so the resource's own BGM starts without the menu tune. */
    j       0x00183220
    addiu   $a0,$zero,2

.align 4
gallery_effect_shift:
    /* Record "0x14 gallery_effect_shift, dx, dz" (float bits): moves the running
     * effect by a fraction of a tile. Pool entries are 0x50 bytes from 00629b80,
     * the world position is at +0x40 and the effect reads it every frame. */
    lui     $t0,0x0062
    lw      $t1,-0x2148($t0) /* 0061deb8 current record */
    lui     $t2,0x004d
    lh      $t3,-0x50cc($t2) /* 004caf34 effect slot of the last 0x56 */
    sll     $t4,$t3,6
    sll     $t3,$t3,4
    addu    $t4,$t4,$t3
    lui     $t5,0x0063
    addu    $t4,$t4,$t5
    lwc1    $f0,-0x6440($t4) /* 00629bc0 x */
    lwc1    $f1,8($t1)
    add.s   $f0,$f0,$f1
    swc1    $f0,-0x6440($t4)
    lwc1    $f0,-0x6438($t4) /* 00629bc8 z */
    lwc1    $f1,12($t1)
    add.s   $f0,$f0,$f1
    jr      $ra
    swc1    $f0,-0x6438($t4)

.align 4
gallery_bgm_nowait:
    /* Record "0x14 gallery_bgm_nowait, 0, track": circle mode's stand-in for op
     * 0x43 (mode words). It makes the same FUN_00182fc0(track, 0, 0, 1, 3, 0)
     * call but does not hold the script until the stream is ready (0x43 waits
     * on the sound-busy word 00620890, about 40 frames), so the track loads
     * while the camera settles and the effect loads. */
    lui     $t0,0x0062
    lw      $t1,-0x2148($t0) /* 0061deb8 current record */
    lw      $a0,12($t1)
    daddu   $a1,$zero,$zero
    daddu   $a2,$zero,$zero
    addiu   $a3,$zero,1
    addiu   $t0,$zero,3
    j       0x00182fc0
    daddu   $t1,$zero,$zero

.align 4
gallery_form_se:
    /* Form-change sound of script op 0x1d (FUN_00182a50(0x2a, 1)); the gallery
     * swaps the unit by remove + spawn because a prepared unit has no linked
     * form objects for 0x1d to switch to. */
    addiu   $a0,$zero,0x2a
    j       0x00182a50
    addiu   $a1,$zero,1

.align 4
.globl gallery_deploy
gallery_deploy:
    /* a0: {member records, squads, groups} of a gallery-owned spawn group.
     * A stage entry installs these tables (0061e158 / 0061e160 / 0061e168)
     * and spawns a group at once with FUN_00181a20 (op 0x05 n with 0x8000):
     * each member gets its own unit and pilot objects, so generic enemy
     * pilots do not collapse onto one actor as in a spawn list. The scene
     * stage's own table pointers are put back afterwards. */
    addiu   $sp,$sp,-0x30
    sd      $ra,0x28($sp)
    lui     $t0,0x0062
    lw      $t1,-0x1ea8($t0)
    lw      $t2,-0x1ea0($t0)
    lw      $t3,-0x1e98($t0)
    sw      $t1,0x10($sp)
    sw      $t2,0x14($sp)
    sw      $t3,0x18($sp)
    lw      $t1,0($a0)
    lw      $t2,4($a0)
    lw      $t3,8($a0)
    sw      $t1,-0x1ea8($t0)
    sw      $t2,-0x1ea0($t0)
    sw      $t3,-0x1e98($t0)
    daddu   $a0,$zero,$zero
    daddu   $a1,$zero,$zero
    jal     0x00181a20
    daddu   $a2,$zero,$zero
    lui     $t0,0x0062
    lw      $t1,0x10($sp)
    lw      $t2,0x14($sp)
    lw      $t3,0x18($sp)
    sw      $t1,-0x1ea8($t0)
    sw      $t2,-0x1ea0($t0)
    sw      $t3,-0x1e98($t0)
    ld      $ra,0x28($sp)
    jr      $ra
    addiu   $sp,$sp,0x30

/* gallery_bgm_restore (out of the 0x1800 block, which the state-region list fills) */
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

/* Circle-mode stand-in for a map-dialogue section. Triangle moves the cursor per
 * line through the record methods 0x221b30 (FUN_0017cd20 speaker lookup) and
 * 0x221b40 (FUN_0017d3c0 polled each frame: FUN_0013d850 sets the cursor, the
 * camera scrolls, then the shown squad member is picked). The talk record becomes
 * "0x52 gallery_quiet_sub, pilots, next" (gosub); per line the subroutine looks
 * the speaker up and polls FUN_0017d3c0 once a frame until the move is done, so
 * the cursor, its visibility and the camera follow the same path without the
 * text, and a line that does not move the cursor costs no frame. (Ext op 0x139c
 * also waits for the camera, but it waits for every static effect too, which a
 * running charge effect 0x13a3 never ends.) */
.align 4
gallery_quiet_sub:
    .word 0x14,gallery_quiet_line,0,0
gallery_quiet_poll:
    .word 0x14,gallery_quiet_scroll,0,0
    .word 0x01,1,0,0
    .word 0x14,gallery_quiet_again,0,0
gallery_quiet_end:
    .word 0x54,0,0,0

.align 4
gallery_quiet_line:
    addiu   $sp,$sp,-0x10
    sd      $ra,0x00($sp)
    lui     $t0,0x0062
    lw      $t1,-0x2110($t0) /* 0061def0 gosub depth */
    sll     $t1,$t1,2
    addu    $t1,$t1,$t0
    lw      $t1,-0x2134($t1) /* 0061ded0[depth - 1]: talk record + 16 */
    lw      $t2,-8($t1)      /* pilots */
    lw      $t3,-4($t1)      /* next line */
    sll     $t4,$t3,1
    addu    $t4,$t4,$t2
    lhu     $a0,0($t4)
    ori     $t5,$zero,0xffff
    bne     $a0,$t5,quiet_line_lookup
    addiu   $t3,$t3,1
    sw      $zero,-4($t1)
    lui     $t1,%hi(gallery_quiet_end - 16)
    addiu   $t1,$t1,%lo(gallery_quiet_end - 16)
    b       quiet_line_done
    sw      $t1,-0x2148($t0) /* the interpreter advances onto the return */
quiet_line_lookup:
    sw      $t3,-4($t1)
    jal     0x0017cd20
    sw      $zero,-0x1f78($t0) /* 0061e088 = 0, as op 0x0f n,0 sets it */
    lh      $t1,-0x78e0($gp)
    addiu   $t2,$zero,1
    beq     $t1,$t2,quiet_line_move
    lui     $t0,0x0062
    lui     $t1,%hi(gallery_quiet_sub - 16)
    addiu   $t1,$t1,%lo(gallery_quiet_sub - 16)
    b       quiet_line_done
    sw      $t1,-0x2148($t0) /* no move: on to the next line */
quiet_line_move:
    jal     0x0017d3c0       /* state 1: FUN_0013d850, then state 3 (scrolling) */
    nop
quiet_line_done:
    ld      $ra,0x00($sp)
    jr      $ra
    addiu   $sp,$sp,0x10

.align 4
gallery_quiet_scroll:
    addiu   $sp,$sp,-0x10
    sd      $ra,0x00($sp)
    jal     0x0017d3c0       /* 3: scrolling; 3 -> 4 picks the shown squad member; 4: done */
    nop
    beq     $v0,$zero,quiet_scroll_wait
    lui     $t0,0x0062
    lui     $t1,%hi(gallery_quiet_sub - 16)
    addiu   $t1,$t1,%lo(gallery_quiet_sub - 16)
    sw      $t1,-0x2148($t0) /* done: next line */
quiet_scroll_wait:
    ld      $ra,0x00($sp)
    jr      $ra
    addiu   $sp,$sp,0x10

.align 4
gallery_quiet_again:
    lui     $t0,0x0062
    lui     $t1,%hi(gallery_quiet_poll - 16)
    addiu   $t1,$t1,%lo(gallery_quiet_poll - 16)
    jr      $ra
    sw      $t1,-0x2148($t0) /* poll again (after the one-frame wait) */

.align 4
.include "gallery-quiet.inc"

/* Only the gallery's reserved w slot uses a private raster. */
.align 4
gallery_private_upload:
    addu    $t4,$t2,$t1
    ori     $at,$zero,0x7f20 /* 113 * 288 */
    bne     $t1,$at,private_upload_done
    nop
    lui     $t4,0x0082
    b       private_upload_done
    ori     $t4,$t4,0x1400
private_upload_done:
    j       0x0013d0d4
    addu    $t3,$t0,$a2
