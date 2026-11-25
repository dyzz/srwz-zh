# Classic mode uses the original display registers. In widescreen mode, fixed
# compositions occupy the central 4:3 area and the tactical map uses the full width.
.include "wide.inc"
.ifdef BITMAP_BEZEL
.ifdef HD_TEXTURE
.equ TEXTURE_FIELD_BYTES,236800
.equ BITMAP_PACKET,80+TEXTURE_FIELD_BYTES
.else
.equ BITMAP_PACKET, 80+16+24*40*112*2
.endif
.endif
.ifdef PNACH
.set noreorder
.set noat
.text
.else
.set WIDE_PANEL, 1
.include "lang_hook.S"
.endif
.align 2

map_projection:
        lw      $t0,wide_enabled
        li      $t2,0x40266666          # stock compass X = 2.6
        beqz    $t0,compass_origin
        lui     $t3,%hi(COMPASS_VECTOR)
        li      $t2,0x406ccccd          # visual shift matching the 80-pixel HUD gutter
compass_origin:
        sw      $t2,%lo(COMPASS_VECTOR)($t3)
        beqz    $t0,original_projection
        lui     $t1,%hi(map_drawn)
        li      $t0,1
        sw      $t0,%lo(map_drawn)($t1)
        # An unchanged matrix may be submitted by several layers in one field.
        # Preserve the actual focal length (including a camera reinitialization).
        la      $t0,projection_state
        li      $t1,TERRAIN_X
        move    $t7,$ra
        bal     scale_projection
        nop
        li      $t1,UNIT_X
        bal     scale_projection
        addiu   $t0,$t0,8
        move    $ra,$t7
original_projection:
        j       PROJECTION_UPDATE
        nop
scale_projection:
        lw      $t2,0($t1)
        lw      $t3,4($t0)
        beq     $t2,$t3,scaled
        lui     $t4,0x3f40
        mtc1    $t2,$f4
        mtc1    $t4,$f5
        sw      $t2,0($t0)
        mul.s   $f4,$f4,$f5
        mfc1    $t3,$f4
        sw      $t3,4($t0)
        sw      $t3,0($t1)
scaled: jr      $ra
        nop

display_output:
        la      $t0,map_drawn
        lw      $t1,0($t0)
        bnez    $t1,stock_display
        sw      $zero,0($t0)
        # Restore both stock matrices when the frame no longer contains a map.
        la      $t0,projection_state
        li      $t1,TERRAIN_X
        move    $t7,$ra
        bal     restore_projection
        nop
        li      $t1,UNIT_X
        bal     restore_projection
        addiu   $t0,$t0,8
        move    $ra,$t7

        lw      $t0,wide_enabled
        andi    $t2,$v0,0x7fff
        beqz    $t0,stock_display
        li      $t1,0x1800
        beq     $t2,$t1,movie_display
        li      $t1,0x18b4
        beq     $t2,$t1,movie_display
        nop
        lui     $t0,%hi(movie_ready)
        b       stock_display
        sw      $zero,%lo(movie_ready)($t0)
movie_display:
        # Sample RGB from the decoder's macroblock buffer. The RGB OR is
        # sufficient for a near-black test; ignore the constant alpha byte.
        lw      $t0,MOVIE_PIXELS
        beqz    $t0,center_display
        move    $t3,$zero
        lui     $t1,8
        addu    $t1,$t1,$t0
movie_sample:
        lwu     $t2,124($t0)
        addiu   $t0,$t0,4096
        bne     $t0,$t1,movie_sample
        or      $t3,$t3,$t2
        srl     $t1,$t3,16
        or      $t1,$t1,$t3
        srl     $t2,$t3,8
        or      $t1,$t1,$t2
        andi    $t1,$t1,255
        sll     $t1,$t1,2
        sltiu   $t2,$t1,128
        bnez    $t2,movie_level
        nop
        li      $t1,128
movie_level:
        addiu   $t3,$t1,1
        lw      $t0,movie_ready
        beq     $t0,$t3,center_display
        lui     $t0,%hi(movie_ready)
        sw      $t3,%lo(movie_ready)($t0)
        # The MPEG player exclusively owns two 768x480 RGBA surfaces at GS
        # pages 0 and 180. Draw circuit 2's plate just after the second one.
        addiu   $sp,$sp,-64
        sd      $ra,0($sp)
        sw      $t1,20($sp)
        li      $t0,0x1000a000
movie_wait_gif:
        lw      $t1,0($t0)
        andi    $t1,$t1,256
        li      $a0,HUD_ARENA+0x30000000
        bnez    $t1,movie_wait_gif
        nop
        dli     $t1,0x1000000000008001
        sd      $t1,0($a0)
        li      $t1,14
        sd      $t1,8($a0)
        li      $t1,0xa0168
        sd      $t1,16($a0)
        li      $t1,0x4c
        sd      $t1,24($a0)
        li      $v0,1                   # movie reads 448 rows per frame
        bal     bezel_append
        addiu   $a0,$a0,32
        li      $t0,0x1000a000
        li      $t2,HUD_ARENA
        sw      $t2,16($t0)
.ifdef BITMAP_BEZEL
        li      $t2,(32+BITMAP_PACKET)/16
.else
        li      $t2,(96+128*((bezel_shapes_end-bezel_shapes)/7))/16
.endif
        sw      $t2,32($t0)
        sync
        li      $t2,257
        sw      $t2,0($t0)
        ld      $ra,0($sp)
        ld      $v1,24($s0)
        ld      $v0,16($s0)
        li      $a1,0x120000a0
        addiu   $a0,$a1,64
        addiu   $a2,$a1,-16
        addiu   $sp,$sp,64
center_display:
        # Circuit 2 defines the original timing. Circuit 1 reads the same full
        # framebuffer at MAGH=2, leaving 80 native pixels on each side.
        # The movie plate uses circuit 2.
        dsrl    $t0,$v1,32
        andi    $t0,$t0,0xfff
        li      $t1,2559
        bne     $t0,$t1,stock_display
        nop
        srl     $t0,$v1,23
        andi    $t0,$t0,15
        li      $t1,3
        bne     $t0,$t1,stock_display
        nop
        sd      $v0,-32($a2)           # DISPFB1
        li      $t0,-640
        dsll32  $t0,$t0,0
        li      $t1,-8388288            # MAGH minus one, DX plus 320 dot clocks
        daddu   $t0,$t0,$t1
        daddu   $t0,$t0,$v1
        sd      $t0,-32($a1)           # DISPLAY1
        ori     $t0,$zero,0xffe7        # opaque circuit 1 over black BGCOLOR
        lw      $t1,movie_ready
        beqz    $t1,center_pmode
        li      $t1,0x1568              # DISPFB2: FBP=360, FBW=10
        sd      $t1,0($a2)
        ori     $t0,$zero,0xff67
center_pmode:
        sd      $t0,-160($a1)          # PMODE
stock_display:
        sd      $v1,0($a1)
        j       DISPLAY_RETURN
        ld      $v0,32($s0)
restore_projection:
        lw      $t2,4($t0)
        beqz    $t2,restored
        lw      $t3,0($t1)
        bne     $t2,$t3,restored
        sw      $zero,4($t0)
        lw      $t2,0($t0)
        sw      $t2,0($t1)
restored:
        jr      $ra
        nop
.align 2
movie_ready: .word 0
wide_enabled:
.ifdef PNACH
        .word 1
.else
        .word 0
.endif
map_drawn: .word 0
projection_state: .space 16
.ifndef PNACH
.include "aspect_text.inc"
.endif
.align 2
.include "hud.S"

.include "bezel.S"
