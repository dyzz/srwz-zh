/* native-tail-r5: shared Original / Best / Special Disc build source.
 * Exactly one world update per display frame. Real resource waits untouched.
 * Reuse only a verified native [21,1e,1f] suffix, let 21 execute normally,
 * then bypass animation wait 1e after object updates. Never clear busy flags.
 * Queue generation counters come from the real append entry when write==0.
 * All unknown scene queues continue with native fast mode (no forced terminal).
 */
.set noreorder
.set noat
.set mips3
.text
.ifndef CTX_SHIFT
.set CTX_SHIFT,0
.endif
.ifndef SCENE_STRIDE
.set SCENE_STRIDE,0x1160
.endif
.org 0
hook:
    addiu $sp,$sp,-0x30
    sd $ra,0x28($sp)
    sd $s0,0x20($sp)
    sd $s1,0x18($sp)
    sd $s2,0x10($sp)
    lui $s2,%hi(DATA)
    addiu $s2,$s2,%lo(DATA)
    lw $t0,0x20($s2)
    addiu $t0,$t0,1
    sw $t0,0x20($s2)
    lui $t3,%hi(CTX)
    lbu $t0,%lo(CTX+CTX_SHIFT)($t3)
    lbu $t1,%lo(CTX+CTX_SHIFT+3)($t3)
    or $t0,$t0,$t1
    bnez $t0,cancel
    nop
    lw $t5,%lo(ACTION_INDEX)($t3)
    lw $t0,0($s2)
    beqz $t0,press
    nop
    lw $t1,4($s2)
    bne $t5,$t1,cancel
    nop
    b active
    nop
press:
    lui $t0,%hi(PAD_TRIG)
    lhu $t0,%lo(PAD_TRIG)($t0)
    andi $t0,$t0,0x80
    beqz $t0,step
    nop
    addiu $t0,$zero,1
    sw $t0,0($s2)
    sw $t5,4($s2)
    sw $zero,0x80($s2)
    sw $zero,0xa0($s2)
    lw $t0,8($s2)
    addiu $t0,$t0,1
    sw $t0,8($s2)
active:
    /* Never accelerate or redirect while resources are busy. */
    lbu $t0,%lo(CTX+CTX_SHIFT+1)($t3)
    lui $t1,%hi(READ_BUSY)
    lw $t1,%lo(READ_BUSY)($t1)
    or $t0,$t0,$t1
    bnez $t0,load_wait
    nop
    addiu $t0,$zero,1
    sb $t0,%lo(CTX+CTX_SHIFT+2)($t3)            /* native fast flag */
    sb $zero,%lo(CTX+CTX_SHIFT+6)($t3)          /* full tick, one world call only */
    lw $t0,0x14($s2)
    addiu $t0,$t0,1
    sw $t0,0x14($s2)
    beqz $t5,step                 /* intro: native fast, no scene surgery */
    nop
    /* Bound the action before dereferencing its scene count. */
    lw $t0,%lo(ACTION_COUNT)($t3)
    sltu $t0,$t5,$t0
    beqz $t0,step
    nop
    addiu $t0,$zero,0x1d4
    multu $t5,$t0
    mflo $t0
    addu $t0,$t0,$t3
    lw $s0,%lo(ACTION_SCENE_COUNT)($t0)
    addiu $t0,$s0,-1
    sltiu $t0,$t0,2
    beqz $t0,step
    nop
    lui $s1,%hi(WORLD)
    addiu $s1,$s1,%lo(WORLD)       /* world */
    lbu $t0,0x402($s1)
    lbu $t1,0x400($s1)
    sltu $t1,$t0,$t1
    beqz $t1,step
    nop
    sll $t0,$t0,3
    addu $t0,$t0,$s1
    lhu $t1,0xe0($t0)
    addiu $t2,$zero,0x11
    beq $t1,$t2,both
    nop
    addiu $t2,$zero,0x2b
    beq $t1,$t2,both
    nop
    addiu $t2,$zero,0x2c
    beq $t1,$t2,selected
    nop
    addiu $t2,$zero,0x2e
    bne $t1,$t2,step
    nop
selected:
    lw $t0,0xe4($t0)            /* world payload: watched scene index */
    lui $t1,0x0010
    sltu $t1,$t0,$t1
    bnez $t1,step
    nop
    lui $t1,0x0200
    sltu $t1,$t0,$t1
    beqz $t1,step
    nop
    lbu $t0,0($t0)
    sltu $t1,$t0,$s0
    beqz $t1,step
    nop
    beqz $t0,scene0_only
    nop
    b scene1
    nop
both:
    addiu $a0,$s1,0x3a80
    addiu $a1,$s2,0x80
    lw $a2,0x40($s2)
    bal close_scene
    nop
    addiu $t0,$zero,2
    bne $s0,$t0,step
    nop
scene1:
    addiu $a0,$s1,(0x3a80+SCENE_STRIDE)
    addiu $a1,$s2,0xa0
    lw $a2,0x44($s2)
    bal close_scene
    nop
    b step
    nop
scene0_only:
    addiu $a0,$s1,0x3a80
    addiu $a1,$s2,0x80
    lw $a2,0x40($s2)
    bal close_scene
    nop
    b step
    nop
load_wait:
    lw $t0,0x24($s2)
    addiu $t0,$t0,1
    sw $t0,0x24($s2)
    b step
    nop
cancel:
    lw $t0,0($s2)
    beqz $t0,step
    nop
    sw $zero,0($s2)
    lw $t0,0x18($s2)
    addiu $t0,$t0,1
    sw $t0,0x18($s2)
step:
    lui $a0,%hi(WORLD)
    jal FN_WORLD_STEP
    addiu $a0,$a0,%lo(WORLD)
    sw $v0,0x10($s2)
    beqz $v0,ret
    nop
    sw $zero,0($s2)
ret:
    ld $ra,0x28($sp)
    ld $s0,0x20($sp)
    ld $s1,0x18($sp)
    ld $s2,0x10($sp)
    jr $ra
    addiu $sp,$sp,0x30

.org 0x300
/* a0=scene, a1=ticket, a2=current scene generation, s1=world, s2=data.
 * Only t/v registers clobbered. One ticket per scene per request.
 */
close_scene:
    lw $t0,0($a1)
    addiu $t1,$zero,2
    beq $t0,$t1,close_ret
    nop
    lw $t1,4($a0)               /* scene allocated */
    beqz $t1,close_ret
    nop
    lw $t8,0x394($a0)           /* animation object must have started */
    beqz $t8,close_ret
    nop
    lbu $t2,0x338($a0)
    addiu $t3,$t2,-3
    sltiu $t4,$t3,98            /* 3 <= count <= 100, queue area 0x320 */
    beqz $t4,close_ret
    nop
    sll $t4,$t3,3
    addu $t4,$t4,$a0
    lhu $t5,0x18($t4)
    addiu $t6,$zero,0x21
    bne $t5,$t6,close_ret
    nop
    lhu $t5,0x20($t4)
    addiu $t6,$zero,0x1e
    bne $t5,$t6,close_ret
    nop
    lhu $t5,0x28($t4)
    addiu $t6,$zero,0x1f
    bne $t5,$t6,close_ret
    nop
    lbu $t7,0x33a($a0)
    sltu $t5,$t7,$t2
    beqz $t5,close_ret
    nop
    /* No redirect while a sprite is loading or pending destruction. */
    addiu $t4,$s1,0x450
    addiu $v0,$zero,2
sprite_group:
    addiu $v1,$zero,4
sprite_slot:
    lbu $t5,0($t4)
    addiu $t6,$zero,2
    beq $t5,$t6,close_ret
    nop
    addiu $t6,$zero,3
    beq $t5,$t6,close_ret
    nop
    addiu $t6,$zero,6
    beq $t5,$t6,close_ret
    nop
    addiu $t4,$t4,0x510
    addiu $v1,$v1,-1
    bnez $v1,sprite_slot
    nop
    addiu $t4,$t4,0x80          /* group stride 0x14c0 - 4*0x510 */
    addiu $v0,$v0,-1
    bnez $v0,sprite_group
    nop
    lw $t9,0x48($s2)            /* world queue generation */
    lbu $t6,0x402($s1)
    beqz $t0,start_close
    nop
    lw $t4,4($a1)
    bne $t4,$a2,stale
    nop
    lw $t4,8($a1)
    bne $t4,$t8,stale
    nop
    lw $t4,0xc($a1)
    bne $t4,$t9,stale
    nop
    lw $t4,0x10($a1)
    bne $t4,$t6,stale
    nop
    lw $t4,0x14($a1)
    bne $t4,$t3,stale
    nop
    addiu $t4,$t3,1
    beq $t7,$t4,terminal
    nop
    beq $t7,$t3,close_ret      /* cleanup has not executed yet */
    nop
    b stale
    nop
start_close:
    addiu $t4,$t3,1
    beq $t7,$t4,terminal      /* native cleanup already completed */
    nop
    sltu $t4,$t3,$t7
    bnez $t4,close_ret        /* already terminal, never rewind */
    nop
    sw $a2,4($a1)
    sw $t8,8($a1)
    sw $t9,0xc($a1)
    sw $t6,0x10($a1)
    sw $t3,0x14($a1)
    addiu $t0,$zero,1
    sw $t0,0($a1)
    sb $t3,0x33a($a0)         /* execute native cleanup in ordinary world step */
    lw $t0,0xc($s2)
    addiu $t0,$t0,1
    sw $t0,0xc($s2)
    jr $ra
    nop
terminal:
    addiu $t3,$t3,2
    sb $t3,0x33a($a0)         /* cleanup done; omit the animation-only tail wait */
    lw $t0,0x2c($s2)
    addiu $t0,$t0,1
    sw $t0,0x2c($s2)
    addiu $t0,$zero,2
    sw $t0,0($a1)
    jr $ra
    nop
stale:
    lw $t0,0x28($s2)
    addiu $t0,$t0,1
    sw $t0,0x28($s2)
    addiu $t0,$zero,2
    sw $t0,0($a1)
close_ret:
    jr $ra
    nop

.org 0x500
/* Queue append entry: originally lbu v0,0x320(a0); sll v0,v0,3.
 * Observe first append after reset, preserving original arguments and result.
 */
queue_append:
    /* Use only v0/a3, both overwritten by original leaf. EE main RAM aliases
       0x2/0x3....... map to the same low RAM; normalize only for comparison. */
    lbu $v0,0x320($a0)
    bnez $v0,append_pass
    nop
    lui $a3,%hi(DATA)
    sw $a0,%lo(DATA+0x50)($a3)  /* raw incoming pointer for runtime evidence */
    sll $v0,$a0,4
    srl $v0,$v0,4
    lui $a3,%hi(SCENE_QUEUE)
    addiu $a3,$a3,%lo(SCENE_QUEUE)
    beq $v0,$a3,gen0
    nop
    addiu $a3,$a3,SCENE_STRIDE
    beq $v0,$a3,gen1
    nop
    addiu $a3,$a3,-(SCENE_STRIDE+0x39b8)
    bne $v0,$a3,append_pass
    nop
    lui $a3,%hi(DATA)
    b gen_inc
    addiu $a3,$a3,%lo(DATA+0x48)
gen0:
    lui $a3,%hi(DATA)
    b gen_inc
    addiu $a3,$a3,%lo(DATA+0x40)
gen1:
    lui $a3,%hi(DATA)
    addiu $a3,$a3,%lo(DATA+0x44)
gen_inc:
    lw $v0,0($a3)
    addiu $v0,$v0,1
    sw $v0,0($a3)
append_pass:
    lbu $v0,0x320($a0)
    sll $v0,$v0,3
    j FN_APPEND_RESUME
    nop

.org 0x600
data:
    .word 0,0,0,0              /* active, action, requests, cleanup redirects */
    .word 0,0,0,0x4e540005     /* world result, fast frames, cancel, marker */
    .word 0,0,0,0              /* calls, resource wait frames, stale, terminal */
    .space 0x10
    .word 0,0,0               /* scene0, scene1, world generations */
    .space 0x34
    .space 0x40               /* tickets [phase,gen,object,wgen,wpc,tail,_,_] */
