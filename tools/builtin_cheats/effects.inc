# End of game tick. Mirror the training roster's 243 player slots and use
# native PP eligibility (pilot master flags bit 4) for existing and new pilots.
cheat_tick:
        lbu $t0,applied+1
        andi $t1,$t0,1
        beqz $t1,bs_check
        nop
        li $t3,999999999
        lui $t1,0x56
        sw $t3,-31392($t1)
bs_check:
        andi $t0,$t0,2
        beqz $t0,pp_check
        nop
        li $t3,999999
        lui $t1,0x56
        sw $t3,-31320($t1)
pp_check:
        lbu $t0,applied+2
        beqz $t0,tick_done
        nop
        li $t1,0x525dc0
        li $t2,243
        li $t4,99999
tick_pilot:
        lbu $t3,62($t1)
        andi $t3,$t3,0x81
        li $t5,1
        bne $t3,$t5,tick_next
        lw $t3,0($t1)
        beqz $t3,tick_next
        nop
        lbu $t3,86($t3)
        andi $t3,$t3,16
        beqz $t3,tick_next
        nop
        sw $t4,148($t1)
tick_next:
        addiu $t2,$t2,-1
        bnez $t2,tick_pilot
        addiu $t1,$t1,176
tick_done:
        j 0x3e26c0
        nop

# Mid-function branches use k0 as scratch, preserving the EE compiler's
# live registers, including at. The original delay instructions are replayed.
money_reward:
        lbu $k0,applied
        addiu $k0,$k0,-1
        bnez $k0,1f
        lw $v1,4($a0)
        sll $s1,$s1,2
1:      j 0x253988
        addu $v1,$v1,$s1
pp_reward:
        lbu $k0,applied
        addiu $k0,$k0,-1
        bnez $k0,1f
        andi $t1,$a1,65535
        sll $t1,$t1,2
        sll $a3,$a3,2
1:      j 0x253b18
        andi $a3,$a3,65535
.macro spirit_hook name,pilot,dest,base,offset,ret,delay
\name:
        lbu $k0,applied+3
        beqz $k0,1f
        lbu \dest,\offset(\base)
        lbu $k0,62(\pilot)
        andi $k0,$k0,1
        beqz $k0,1f
        nop
        move \dest,$zero
1:      j \ret
        \delay
.endm
spirit_hook cost_apply,$a0,$v0,$a3,2,cost_call,"nop"
cost_call:
        jal 0x2777e0
        negu $a1,$v0
        j 0x289710
        nop
spirit_hook cost_list,$s6,$v1,$a2,102,0x35df8c,"sh $v1,6($s5)"
spirit_hook cost_check,$s3,$v0,$v0,102,0x37f32c,"slt $at,$v1,$v0"

bs_reward:
        dsra32 $a1,$v1,17
        lbu $k0,applied
        beqz $k0,1f
        nop
        sll $a1,$a1,2
1:      j 0x253a20
        lw $v1,8($a0)
xp_reward:
        lbu $k0,applied
        beqz $k0,1f
        lw $v1,176($sp)
        sll $s3,$s3,2
1:      j 0x253e10
        lui $at,0x5a
energy_cost:
        lbu $k0,applied+4
        beqz $k0,1f
        nop
        move $v1,$zero
1:      subu $v1,$v0,$v1
        j 0x280b54
        sh $v1,242($a0)
ammo_cost:
        lbu $k0,applied+4
        bnez $k0,1f
        nop
        addiu $v1,$v1,-1
1:      j 0x280c00
        sb $v1,4($s0)
upgrade_limit:
        lbu $k0,applied+5
        beqz $k0,1f
        nop
        li $v0,15
1:      jr $ra
        nop
parts_query:
        addu $v0,$v0,$v1
        lbu $k0,applied+6
        beqz $k0,1f
        nop
        li $k0,99
        sb $k0,0($v0)
1:      j 0x276408
        lb $v0,0($v0)
