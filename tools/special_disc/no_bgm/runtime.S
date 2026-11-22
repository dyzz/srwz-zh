.set noreorder
.set noat
.text
.equ NO_BGM, 0x7e
.global settings_init, settings_confirm, option_names, option_help
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
    li $9,NO_BGM
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
    ld $31,16($29)
    jr $31
    addiu $29,$29,32
settings_confirm:
    lb $3,4($4)
    li $2,3
    beq $3,$2,select_silence
    nop
    # Restore a real selection before the native handler applies the new mode.
    lui $8,0x76
    lw $8,0x33e8($8)
    lh $9,0x9a($8)
    li $2,NO_BGM
    bne $9,$2,native_confirm
    nop
    addiu $29,$29,-32
    sd $31,16($29)
    sd $4,8($29)
    jal leader_song
    nop
    lui $4,0x76
    lw $4,0x33e8($4)
    jal 0x4115e0
    move $5,$2
    ld $4,8($29)
    ld $31,16($29)
    addiu $29,$29,32
native_confirm:
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
    jal 0x4115e0
    li $5,NO_BGM
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

format_song:
    li $2,NO_BGM
    beq $4,$2,no_song_name
    nop
    j 0x41154c
    li $2,0x66
no_song_name:
    lui $6,%hi(silence_label)
    j 0x4115ac
    addiu $6,$6,%lo(silence_label)
song_icon:
    li $3,NO_BGM
    beq $2,$3,plain
    slti $2,$2,0x66
    beqz $2,random
    nop
plain:
    j 0x422088
    li $4,14
random:
    j 0x42207c
    li $4,14
# The deserializer refreshes the display from the saved +0x9a field.
restore_song:
    li $2,101
    bne $5,$2,restore_native
    nop
    lbu $2,0x98($4)
    andi $2,$2,12
    li $3,8
    bne $2,$3,restore_native
    nop
    li $5,NO_BGM
    sh $5,0x9a($4)
restore_native:
    j 0x411510
    nop

# Preserve the selected leader side in the native settings. Unit changes
# can still update both rosters while the music selection stays muted.
auto_song:
    lh $2,0x9a($4)
    li $3,NO_BGM
    beq $2,$3,auto_done
    nop
    addiu $29,$29,-64
    j 0x411638
    li $3,1
auto_done:
    jr $31
    move $2,$0

select_music_cursor:
    li $2,NO_BGM
    bne $5,$2,native_cursor
    nop
    move $5,$0
native_cursor:
    j 0x340b40
    nop

.global resolve, volume, return_music, mute_flag
resolve:
    li $2,NO_BGM
    beq $4,$2,muted_request
    lui $3,%hi(mute_flag)
    sb $0,%lo(mute_flag)($3)
    j 0x3c1540
    nop
muted_request:
    li $2,1
    sb $2,%lo(mute_flag)($3)
leader_song:
    lui $3,0x76
    lw $3,0x33e8($3)
    lbu $2,0x98($3)
    andi $2,$2,12
    li $4,4
    beq $2,$4,left
    nop
    b leader
    lh $4,8($3)
left:
    lh $4,0x54($3)
leader:
    bltz $4,fallback
    nop
    j 0x4260b0
    nop
fallback:
    jr $31
    li $2,0x38
volume:
    lui $2,%hi(mute_flag)
    lbu $2,%lo(mute_flag)($2)
    movn $5,$0,$2
    j 0x18c8a0
    nop
return_music:
    lui $2,%hi(mute_flag)
    sb $0,%lo(mute_flag)($2)
    j 0x182e30
    nop
mute_flag:
    .word 0
