.equ bitmap_pixels,map_projection+4096

        # Fourth A+D register supplies the fade modulation for both rails.
        lw $t0,20($sp)
        li $t1,0x010101
        multu $t0,$t1
        mflo $t0
        lui $t1,0x8000
        or $t0,$t0,$t1
        sd $t0,0($a0)
        li $t1,1
        sd $t1,8($a0)
        addiu $a0,$a0,16
        la $t0,bitmap_pixels
        li $t1,TEXTURE_FIELD_BYTES
        beqz $v0,texture_copy
        nop
        addu $t0,$t0,$t1
texture_copy:
        addu $t1,$t0,$t1
texture_loop:
        ld $t2,0($t0)
        ld $t3,8($t0)
        sd $t2,0($a0)
        sd $t3,8($a0)
        addiu $t0,$t0,16
        bne $t0,$t1,texture_loop
        addiu $a0,$a0,16
        jr $ra
        nop
