# End of game tick. Mirror the native training roster and use
# native PP eligibility (pilot master flags bit 4) for existing and new pilots.
cheat_tick:
        lbu $t0,applied+1
        andi $t1,$t0,1
        beqz $t1,bs_check
        nop
        li $t3,999999999
        lui $t1,%hi(CASH)
        sw $t3,%lo(CASH)($t1)
bs_check:
        andi $t0,$t0,2
        beqz $t0,pp_check
        nop
        li $t3,999999
        lui $t1,%hi(BS)
        sw $t3,%lo(BS)($t1)
pp_check:
        lbu $t0,applied+2
        beqz $t0,tick_done
        nop
        li $t1,PILOTS
        li $t2,PLAYER_SLOTS
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
        j TICK_DONE
        nop

# Mid-function branches use k0 as scratch, preserving the EE compiler's
# live registers, including at. The original delay instructions are replayed.
money_reward:
        lbu $k0,applied
        addiu $k0,$k0,-1
        bnez $k0,1f
        lw $v1,4($a0)
        sll $s1,$s1,2
1:      j MONEY_REWARD_END
        addu $v1,$v1,$s1
pp_reward:
        lbu $k0,applied
        addiu $k0,$k0,-1
        bnez $k0,1f
        andi $t1,$a1,65535
        sll $t1,$t1,2
        sll $a3,$a3,2
1:      j PP_REWARD_END
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
        jal SP_DEBIT
        negu $a1,$v0
        j COST_APPLY_END
        nop
spirit_hook cost_list,$s6,$v1,$a2,SP_COST,COST_LIST_END,"sh $v1,6($s5)"
spirit_hook cost_check,$s3,$v0,$v0,SP_COST,COST_CHECK_END,"slt $at,$v1,$v0"

bs_reward:
        dsra32 $a1,$v1,17
        lbu $k0,applied
        beqz $k0,1f
        nop
        sll $a1,$a1,2
1:      j BS_REWARD_END
        lw $v1,8($a0)
xp_reward:
        lbu $k0,applied
        beqz $k0,1f
        lw $v1,176($sp)
        sll $s3,$s3,2
1:      j XP_REWARD_END
        lui $at,XP_HIGH
energy_cost:
        lbu $k0,applied+4
        beqz $k0,1f
        nop
        move $v1,$zero
1:      subu $v1,$v0,$v1
        j ENERGY_COST_END
        sh $v1,242($a0)
ammo_cost:
        lbu $k0,applied+4
        bnez $k0,1f
        nop
        addiu $v1,$v1,-1
1:      j AMMO_COST_END
        sb $v1,4($s0)
upgrade_limit:
        lbu $k0,applied+5
        beqz $k0,1f
        nop
        li $v0,15
1:      jr $ra
.if UP_STACK
        addiu $sp,$sp,UP_STACK
.else
        nop
.endif
parts_query:
        addu $v0,$v0,$v1
        lbu $k0,applied+6
        beqz $k0,1f
        nop
        li $k0,99
        sb $k0,0($v0)
1:      j PARTS_QUERY_END
        lb $v0,0($v0)
