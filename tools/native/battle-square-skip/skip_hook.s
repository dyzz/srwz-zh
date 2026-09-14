/* Square-button "skip to next battle action" hook for Super Robot Wars Z.
 *
 * Assembled per edition with absolute symbols supplied through --defsym:
 *   CAVE            code cave inside the executable (0x400 zero bytes)
 *   DATA            state block = CAVE + 0x380
 *   PAD_HELD        game pad "held" mask (u16)      PAD_TRIG  "new press" mask (u16)
 *   CTX             battle input block (bytes: [0] no-more-skip, [2] fast, [3] skip
 *                   request, [6] half-rate tick)
 *   WORLD           battle world object            CURSOR    GS packet cursor (u32)
 *   ACTION_INDEX    current battle action index (u32)
 *   FN_WORLD_STEP   world step function            FN_SPRITE_DRAW  draw-node type 0
 *   FN_SE_RESUME    SE request function, third instruction
 *   FN_FLIP         per-frame display present function
 *
 * Patch sites (per edition, see config): the `jal FN_WORLD_STEP` inside the
 * per-frame battle step becomes `jal CAVE`; the `jal FN_SPRITE_DRAW` inside the
 * draw dispatcher becomes `jal CAVE+0x2C0`; the SE function prologue becomes
 * `j CAVE+0x300; nop`; the main-loop `jal FN_FLIP` becomes `jal CAVE+0x340`.
 *
 * Behaviour: a new square press during a battle action runs up to K extra
 * logic steps per frame (sprites not drawn, sound effects muted, GS packet
 * growth bounded by LIMIT) until the action index changes or the demo ends.
 * The display is not presented while skipping, so the screen keeps the frame
 * shown when square was pressed and cuts straight to the next action.
 */
    .set noreorder
    .set noat
    .set mips3
    .text

    .org 0x000
hook:
    addiu $sp, $sp, -0x20
    sw    $ra, 0x1c($sp)
    sw    $s0, 0x18($sp)
    sw    $s1, 0x14($sp)
    sw    $s2, 0x10($sp)
    lui   $s1, %hi(CURSOR)
    lw    $s1, %lo(CURSOR)($s1)         /* packet cursor at frame start */
    lui   $s2, %hi(DATA)
    addiu $s2, $s2, %lo(DATA)
    lw    $t1, 0($s2)                   /* SKIP_ACTIVE */
    bnez  $t1, extra_init
    nop
    lui   $a0, %hi(WORLD)
    jal   FN_WORLD_STEP                 /* normal step */
    addiu $a0, $a0, %lo(WORLD)
    bnez  $v0, end_clear
    nop
    lui   $at, %hi(PAD_TRIG)
    lhu   $t2, %lo(PAD_TRIG)($at)
    andi  $t2, $t2, 0x0080              /* square */
    beqz  $t2, ret_zero
    nop
    lui   $t3, %hi(CTX)
    lbu   $t4, %lo(CTX)($t3)            /* ctx[0]: final fade reached */
    bnez  $t4, ret_zero
    nop
    lbu   $t4, %lo(CTX+3)($t3)          /* ctx[3]: cross/start skip pending */
    bnez  $t4, ret_zero
    nop
    addiu $t1, $zero, 1
    sw    $t1, 0($s2)                   /* SKIP_ACTIVE = 1 */
    lui   $t5, %hi(ACTION_INDEX)
    lw    $t5, %lo(ACTION_INDEX)($t5)
    sw    $t5, 4($s2)                   /* SKIP_ACTION */
    lw    $t6, 8($s2)
    addiu $t6, $t6, 1
    sw    $t6, 8($s2)                   /* activations */
extra_init:
    lw    $s0, 0x14($s2)                /* K */
loop:
    lui   $t3, %hi(ACTION_INDEX)
    lw    $t5, %lo(ACTION_INDEX)($t3)
    lw    $t6, 4($s2)
    bne   $t5, $t6, deactivate
    nop
    lui   $t3, %hi(CTX)
    addiu $t1, $zero, 1
    sb    $t1, %lo(CTX+2)($t3)          /* ctx[2] fast */
    sb    $zero, %lo(CTX+6)($t3)        /* ctx[6] full tick */
    lw    $t7, 0x34($s2)
    sw    $t7, 0x2c($s2)                /* EXTRA_STEP = SKIP_DRAW_ENABLE */
    lui   $a0, %hi(WORLD)
    jal   FN_WORLD_STEP
    addiu $a0, $a0, %lo(WORLD)
    sw    $zero, 0x2c($s2)
    lw    $t6, 0xc($s2)
    addiu $t6, $t6, 1
    sw    $t6, 0xc($s2)                 /* extra steps */
    bnez  $v0, end_clear
    nop
    lui   $t7, %hi(CURSOR)
    lw    $t7, %lo(CURSOR)($t7)
    subu  $t7, $t7, $s1
    lw    $t8, 0x28($s2)                /* LIMIT */
    sltu  $t8, $t8, $t7
    bnez  $t8, final_step
    nop
    addiu $s0, $s0, -1
    bnez  $s0, loop
    nop
final_step:
    lui   $t3, %hi(ACTION_INDEX)
    lw    $t5, %lo(ACTION_INDEX)($t3)
    lw    $t6, 4($s2)
    bne   $t5, $t6, deactivate
    nop
    lui   $t3, %hi(CTX)
    addiu $t1, $zero, 1
    sb    $t1, %lo(CTX+2)($t3)
    sb    $zero, %lo(CTX+6)($t3)
    lui   $a0, %hi(WORLD)
    jal   FN_WORLD_STEP                 /* full step, never presented */
    addiu $a0, $a0, %lo(WORLD)
    bnez  $v0, end_clear
    nop
    b     ret_zero
    nop
deactivate:
    sw    $zero, 0($s2)                 /* SKIP_ACTIVE = 0: this frame is presented */
    lw    $t6, 0x18($s2)
    addiu $t6, $t6, 1
    sw    $t6, 0x18($s2)                /* deactivations */
    lui   $a0, %hi(WORLD)
    jal   FN_WORLD_STEP                 /* first visible frame of the next action */
    addiu $a0, $a0, %lo(WORLD)
    bnez  $v0, end_clear
    nop
ret_zero:
    b     ret
    addu  $v0, $zero, $zero
end_clear:
    sw    $zero, 0($s2)
    sw    $zero, 0x2c($s2)
    sw    $v0, 0x10($s2)                /* last world-step result */
ret:
    lw    $ra, 0x1c($sp)
    lw    $s0, 0x18($sp)
    lw    $s1, 0x14($sp)
    lw    $s2, 0x10($sp)
    jr    $ra
    addiu $sp, $sp, 0x20

/* CAVE+0x2C0: skip draw-node type 0 (sprite renderer) during extra steps */
    .org 0x2c0
draw0:
    lui   $t0, %hi(DATA+0x2c)
    lw    $t0, %lo(DATA+0x2c)($t0)      /* EXTRA_STEP */
    bnez  $t0, draw_skip
    nop
    j     FN_SPRITE_DRAW
    nop
    .org 0x2e0
draw_skip:
    jr    $ra
    nop

/* CAVE+0x300: SE request prologue, muted while skipping */
    .org 0x300
se_stub:
    lui   $t0, %hi(DATA+0x30)
    lw    $t0, %lo(DATA+0x30)($t0)      /* MUTE_SE_ENABLE */
    beqz  $t0, se_pass
    nop
    lui   $t0, %hi(DATA)
    lw    $t0, %lo(DATA)($t0)           /* SKIP_ACTIVE */
    bnez  $t0, se_mute
    nop
se_pass:
    addiu $sp, $sp, -0x70               /* replayed prologue */
    sd    $ra, 0x50($sp)
    j     FN_SE_RESUME
    nop
se_mute:
    jr    $ra
    addu  $v0, $zero, $zero

/* CAVE+0x340: display present, withheld while skipping */
    .org 0x340
flip_stub:
    lui   $t0, %hi(DATA)
    lw    $t0, %lo(DATA)($t0)           /* SKIP_ACTIVE */
    bnez  $t0, flip_skip
    nop
    j     FN_FLIP
    nop
flip_skip:
    jr    $ra
    addu  $v0, $zero, $zero

/* CAVE+0x380: state block */
    .org 0x380
data:
    .word 0            /* +00 SKIP_ACTIVE */
    .word 0            /* +04 SKIP_ACTION */
    .word 0            /* +08 activations (diagnostic) */
    .word 0            /* +0c extra steps (diagnostic) */
    .word 0            /* +10 last world-step result (diagnostic) */
    .word 15           /* +14 K: extra logic steps per frame */
    .word 0            /* +18 deactivations (diagnostic) */
    .word 0x5a5a0010   /* +1c marker / version */
    .word 0            /* +20 reserved */
    .word 0            /* +24 reserved */
    .word 0x00030000   /* +28 LIMIT: packet bytes after which no more extra steps */
    .word 0            /* +2c EXTRA_STEP */
    .word 1            /* +30 MUTE_SE_ENABLE */
    .word 1            /* +34 SKIP_DRAW_ENABLE */
