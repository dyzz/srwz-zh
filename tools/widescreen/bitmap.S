# RGBAQ, XYZ2, XYZ2 for each 2x2 sprite. Explicitly set PRIM because
# PRE only takes effect on packed tags; the whole
# image is one REGLIST packet in the game's current draw context.
        li      $t0,6
        sd      $t0,0($a0)
        sd      $zero,8($a0)
        addiu   $a0,$a0,16
        dli     $t0,0x3400000000008000 + 8960
        sd      $t0,0($a0)
        li      $t0,0x551
        sd      $t0,8($a0)
        addiu   $a0,$a0,16
        la      $t0,bitmap_pixels
        lw      $t5,20($sp)
        li      $t6,0xff00ff
        li      $t7,32
        sllv    $t7,$t7,$v0            # height of one cell in GS subpixels
        sll     $t7,$t7,16
        move    $t1,$zero
bitmap_side:
        move    $t2,$zero              # row Y, in upper half of XYZ2
        li      $t3,112
bitmap_row:
        or      $a1,$t2,$t1            # X starts at 0 or 560 * 16
        li      $t4,40
bitmap_cell:
        lwu     $a2,0($t0)
        and     $a3,$a2,$t6
        multu   $a3,$t5
        mflo    $a3
        srl     $a3,$a3,7
        and     $a3,$a3,$t6
        andi    $a2,$a2,0xff00
        multu   $a2,$t5
        mflo    $a2
        srl     $a2,$a2,7
        andi    $a2,$a2,0xff00
        or      $a3,$a2,$a3
        ori     $a2,$zero,128
        sll     $a2,$a2,24
        or      $a3,$a3,$a2
        sd      $a3,0($a0)
        sd      $a1,8($a0)
        addiu   $a1,$a1,32
        daddu   $a2,$a1,$t7
        sd      $a2,16($a0)
        addiu   $t0,$t0,4
        addiu   $t4,$t4,-1
        bnez    $t4,bitmap_cell
        addiu   $a0,$a0,24
        daddu   $t2,$t2,$t7
        addiu   $t3,$t3,-1
        bnez    $t3,bitmap_row
        nop
        beqz    $t1,bitmap_side
        li      $t1,8960
        jr      $ra
        nop
# Reserve the pixel data in the private heap prefix, outside the boot code.
.ifdef BUILTIN_BITMAP
.equ bitmap_pixels,BUILTIN_BITMAP
.else
.equ bitmap_pixels,map_projection+4096
.endif
