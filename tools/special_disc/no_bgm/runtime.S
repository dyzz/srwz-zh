.set noreorder
.set noat
.text
.global settings_init, settings_confirm, bgm_sync, bgm_async, option_names, option_help
settings_init:
    addiu $29,$29,-32
    sd $31,16($29)
    jal 0x4180f0
    nop
    li $8,4
    sb $8,5($2)
    lui $8,0x76
    lw $8,0x33e8($8)
    lh $8,0x4f4($8)
    li $9,101
    bne $8,$9,init_tables
    nop
    li $8,3
    sb $8,4($2)
    sb $8,6($2)
init_tables:
    lui $8,0x7d
    addiu $8,$8,-0xd10
    lui $9,%hi(option_names)
    addiu $9,$9,%lo(option_names)
    lw $10,0($8)
    lw $11,4($8)
    lw $12,8($8)
    sw $10,0($9)
    sw $11,4($9)
    sw $12,8($9)
    lw $10,16($8)
    lw $11,20($8)
    lw $12,24($8)
    sw $10,16($9)
    sw $11,20($9)
    sw $12,24($9)
    lui $8,0x7d
    addiu $8,$8,-0x7d54
    lui $9,%hi(silence_label)
    addiu $9,$9,%lo(silence_label)
    sw $9,0($8)
    ld $31,16($29)
    jr $31
    addiu $29,$29,32
settings_confirm:
    lb $3,4($4)
    li $2,3
    beq $3,$2,select_silence
    nop
    addiu $29,$29,-32
    j 0x418408
    lui $1,0x76
select_silence:
    addiu $29,$29,-32
    sd $31,16($29)
    sd $4,8($29)
    sb $3,6($4)
    lui $4,0x76
    lw $4,0x33e8($4)
    lbu $2,0x98($4)
    andi $2,$2,0xf3
    ori $2,$2,8
    sb $2,0x98($4)
    jal 0x4115e0
    li $5,101
    ld $4,8($29)
    li $2,1
    sb $2,7($4)
    sh $0,10($4)
    jal 0x3c1520
    li $4,0x13
    ld $31,16($29)
    move $2,$0
    jr $31
    addiu $29,$29,32
bgm_sync:
    li $3,101
    beq $4,$3,silence
    nop
    addiu $29,$29,-0x60
    j 0x182e38
    li $2,3
bgm_async:
    li $3,101
    beq $4,$3,silence
    nop
    addiu $29,$29,-0x70
    j 0x182fc8
    li $2,3
silence:
    addiu $29,$29,-16
    sd $31,0($29)
    jal 0x18b1f0
    nop
    lui $3,0x5e
    li $2,101
    sb $2,-0x4468($3)
    ld $31,0($29)
    li $2,1
    jr $31
    addiu $29,$29,16
.balign 16
silence_label:
.incbin "label.bin"

option_label:
.incbin "option.bin"
help_label:
.incbin "help.bin"
.balign 16
option_names:
.word 0,0,0,option_label
option_help:
.word 0,0,0,help_label
