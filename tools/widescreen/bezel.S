# Each row is a solid trapezoid on the left plate. Reflect its four vertices
# across the 640-pixel framebuffer for the right plate. Y is in field lines.
.align 2
bezel_age: .word 0

# GS colours are packed as 0xBBGGRR, without lighting or texture sampling.
bezel_palette: .word 0x211912,0x352d24,0x463b31,0x211b16,0x524538,0x17110c,0x5b5146,0x3f352c,0x302820,0x211b15,0x231b13
bezel_shapes:
.macro panel palette_offset, y0, y1, l0, r0, l1, r1
        .byte   \palette_offset,\y0,\y1,\l0,\r0,\l1,\r1
.endm
# Vertical frame and inner reveal.
        panel 0,0,224,0,80,0,80
        panel 4,0,224,4,74,4,74
        panel 8,0,224,7,69,7,69
        panel 12,0,224,68,71,68,71
        panel 16,0,224,71,73,71,73
        panel 20,0,224,76,80,76,80
# One-pixel bevel follows the stepped silhouette of the main plate.
        panel 24,0,43,8,66,8,66
        panel 24,43,54,8,66,8,49
        panel 24,54,70,8,49,8,49
        panel 24,70,75,8,49,8,60
        panel 24,75,152,8,60,8,60
        panel 24,152,164,8,60,8,44
        panel 24,164,177,8,44,8,44
        panel 24,177,189,8,44,8,66
        panel 24,189,224,8,66,8,66
        panel 28,0,43,8,65,8,65
        panel 28,43,54,8,65,8,48
        panel 28,54,70,8,48,8,48
        panel 28,70,75,8,48,8,59
        panel 28,75,152,8,59,8,59
        panel 28,152,164,8,59,8,43
        panel 28,164,177,8,43,8,43
        panel 28,177,189,8,43,8,65
        panel 28,189,224,8,65,8,65
# Diagonal joint, ventilation slots, and recessed fasteners.
        panel 32,96,106,13,13,13,58
        panel 32,106,118,13,58,58,58
        panel 36,181,183,15,42,15,42
        panel 36,185,187,15,42,15,42
        panel 36,189,191,15,42,15,42
        panel 40,9,11,15,18,15,18
        panel 40,213,215,15,18,15,18
bezel_shapes_end:
.align 2
# Append one GIFtag per trapezoid. REGLIST: PRIM, RGBAQ, XYZ2 x4.
bezel_append:
        dli     $t0,0x1000000000008003
        sd      $t0,0($a0)
        li      $t0,14
        sd      $t0,8($a0)
        sd      $zero,16($a0)
        li      $t0,0x18                # XYOFFSET_1
        sd      $t0,24($a0)
        dli     $t0,0x01bf0000027f0000
        sd      $t0,32($a0)
        li      $t0,0x40                # SCISSOR_1
        sd      $t0,40($a0)
        sd      $zero,48($a0)
        li      $t0,0x47                # TEST_1
        sd      $t0,56($a0)
        addiu   $a0,$a0,64
        la      $t0,bezel_shapes
        li      $t1,(bezel_shapes_end-bezel_shapes)/7
        dli     $t2,0x6400000000008001 # FLG=REGLIST, NREG=6
        li      $t3,0x555510
bezel_row:
        lbu     $t4,0($t0)
        la      $t5,bezel_palette
        addu    $t4,$t4,$t5
        lwu     $t4,0($t4)
        lw      $t5,20($sp)
        li      $t7,0xff00ff
        and     $t6,$t4,$t7
        multu   $t6,$t5
        mflo    $t6
        srl     $t6,$t6,7
        and     $t6,$t6,$t7
        andi    $t4,$t4,0xff00
        multu   $t4,$t5
        mflo    $t4
        srl     $t4,$t4,7
        andi    $t4,$t4,0xff00
        or      $t4,$t4,$t6
        lui     $t5,0x8000
        or      $t4,$t4,$t5
        lbu     $t5,1($t0)
        lbu     $t6,2($t0)
        sll     $t5,$t5,20
        sll     $t6,$t6,20
        sllv    $t5,$t5,$v0
        sllv    $t6,$t6,$v0
        move    $a1,$zero
bezel_side:
        sd      $t2,0($a0)
        sd      $t3,8($a0)
        li      $t7,4
        sd      $t7,16($a0)
        sd      $t4,24($a0)
        addiu   $a2,$t0,3
        move    $a3,$zero
bezel_corner:
        lbu     $t7,0($a2)
        beqz    $a1,bezel_x
        li      $t8,640
        subu    $t7,$t8,$t7
bezel_x:
        sll     $t7,$t7,4
        sltiu   $t8,$a3,2
        beqz    $t8,bezel_vertex
        move    $t8,$t6
        move    $t8,$t5
bezel_vertex:
        or      $t7,$t7,$t8
        sd      $t7,32($a0)
        addiu   $a0,$a0,8
        addiu   $a3,$a3,1
        sltiu   $t8,$a3,4
        bnez    $t8,bezel_corner
        addiu   $a2,$a2,1
        addiu   $a0,$a0,32
        beqz    $a1,bezel_side
        li      $a1,1
        addiu   $t1,$t1,-1
        bnez    $t1,bezel_row
        addiu   $t0,$t0,7
        jr      $ra
        nop
