.set noat
.set noreorder
.include "edition.inc"
.include "language.inc"
.include "native.inc"
.text
.if SP_EDITION
# The SP widescreen builder replaces the language program in place and relinks these imports.
lang_imports: .word LANG_ID, LANG_SET, LANG_RESTORE
.endif
.macro menu_language reg
.if SP_EDITION
        lw \reg,lang_imports
        lw \reg,0(\reg)
.else
        lw \reg,LANG_ID
.endif
.endm
.globl cheat_home
cheat_home:
        li $t9,HOME_DRAW
        lw $t0,HOME_STATE
        bnez $t0,pass_screen
        nop
        lw $t0,HOME_ROOT
        beqz $t0,pass_screen
        nop
        lui $t1,1
        addu $t0,$t0,$t1
        lw $t1,HOME_SLOT($t0)             # top intermission menu controller
        sll $t1,$t1,2
        addu $t0,$t0,$t1
        lw $t0,HOME_TABLE($t0)
        beqz $t0,pass_screen
        nop
        lw $t0,8($t0)
        lw $t0,20($t0)
        li $t1,HOME_TOP
        bne $t0,$t1,pass_screen
        nop
        b screen
        nop
cheat_map:
        li $t9,MAP_DRAW
        lbu $t0,MAP_MODE
        li $t1,1
        bne $t0,$t1,pass_screen
        nop
        lw $t0,CURSOR_ROOT
        beqz $t0,pass_screen
        nop
        lb $t1,4($t0)
        bltz $t1,pass_screen
        addu $t0,$t0,$t1
        lbu $t1,6($t0)                # native free-cursor controller is slot 0
        bnez $t1,pass_screen
        nop
        lw $t0,MAP_BUSY
        lw $t1,UNIT_BUSY
        or $t0,$t0,$t1
        lw $t1,EVENT_BUSY
        or $t0,$t0,$t1
        bnez $t0,pass_screen
        nop
screen:
        addiu $sp,$sp,-64
        sd $ra,0($sp)
        sd $s0,8($sp)
        sd $s1,16($sp)
        sd $s2,24($sp)
        move $s0,$a0
        move $s2,$t9
        la $s1,settings
        lhu $t0,PAD_PRESSED
        sh $t0,32($sp)
        lbu $t1,17($s1)
        bnez $t1,active
        andi $t1,$t0,0x100            # SELECT on this screen
        beqz $t1,draw_screen
        nop
        ld $t0,0($s1)
        sd $t0,8($s1)
        sb $zero,16($s1)
        li $t0,1
        sb $t0,17($s1)
        lw $t0,MSG_PTR
        sw $t0,20($s1)                # preserve the underlying screen's message box
        jal MB_CREATE
        nop
        lw $t0,MSG_PTR
        sw $t0,24($s1)
        jal refresh
        nop
active:
        la $t0,PAD_PRESSED
        sh $zero,-2($t0)
        sh $zero,0($t0)
        sh $zero,4($t0)
        lw $t0,20($s1)
        lui $t1,%hi(MSG_PTR)
        sw $t0,%lo(MSG_PTR)($t1)
        move $a0,$s0
        jalr $s2
        nop
after_underlying:
        move $s0,$v0
        lui $t1,%hi(MSG_PTR)
        lw $t0,24($s1)
        sw $t0,%lo(MSG_PTR)($t1)
        li $a0,PAD_BUF
        jal MB_INPUT
        nop
        lhu $t0,32($sp)
        andi $t1,$t0,0x40
        bnez $t1,close
        andi $t1,$t0,0x20
        beqz $t1,navigate
        ld $t1,8($s1)
        sd $t1,0($s1)
close:
        jal MB_DESTROY
        nop
.if SP_EDITION
        lw $t9,lang_imports+8
        jalr $t9
.else
        jal LANG_RESTORE
.endif
        nop
        lui $t1,%hi(MSG_PTR)
        lw $t0,20($s1)
        sw $t0,%lo(MSG_PTR)($t1)
        b finish
        sb $zero,17($s1)
navigate:
        andi $t1,$t0,0xf000
        beqz $t1,draw
        lbu $t2,16($s1)
        andi $t1,$t0,0x5000
        beqz $t1,value
        li $t4,7
        addiu $t3,$s1,16
        b step
        andi $t1,$t0,0x1000
value:
        addiu $t3,$s1,8
        addu $t3,$t3,$t2
        li $t4,2
        li $t5,1
        bne $t2,$t5,1f
        nop
        li $t4,4
1:
        lbu $t2,0($t3)
        andi $t1,$t0,0x8000
step:
        beqz $t1,wrap
        addiu $t2,$t2,1
        addu $t2,$t2,$t4
        addiu $t2,$t2,-2
wrap:
        sltu $t1,$t2,$t4
        bnez $t1,changed
        nop
        subu $t2,$t2,$t4
changed:
        sb $t2,0($t3)
draw:
        sd $s0,40($sp)
        li $t0,1
        sb $t0,18($s1)
        move $a0,$s0
        li $a1,BOX_X
        li $a2,BOX_Y+2
        jal MB_DRAW
        move $a3,$zero
        sb $zero,18($s1)
        move $a0,$v0
        li $a1,ICON_SWITCH                 # Small native D-pad with left and right highlighted
        jal cheat_icon
        li $a2,-127
        move $a0,$v0
        li $a1,ICON_OK
        jal cheat_icon
        li $a2,-11
        move $a0,$v0
        li $a1,ICON_CANCEL
        jal cheat_icon
        li $a2,69
        move $s0,$v0
        jal TEXT_PASS
        nop
# SP also depth-tests text behind the map Report window.
.if !SP_EDITION
        li $t0,HOME_DRAW
        bne $s2,$t0,finish
.endif
        ld $a0,40($sp)
        bal foreground
        move $a1,$s0
        b finish
        move $s0,$v0
draw_screen:
        move $a0,$s0
        jalr $s2
        move $a1,$zero
        move $s0,$v0
finish:
        move $v0,$s0
        ld $ra,0($sp)
        ld $s0,8($sp)
        ld $s1,16($sp)
        ld $s2,24($sp)
        jr $ra
        addiu $sp,$sp,64
cheat_icon:
        li $a3,BOX_Y+2+4+88
        move $t0,$zero
        li $t1,128
        j KVP_DRAW
        move $t2,$t1
pass_screen:
        jr $t9
        nop

# Native intermission sprites and the pilot portrait can be nearer in Z
# than the Report window. Keep the native geometry, scissor and alpha test.
# For the Report pass alone, make each emitted GS TEST depth comparison ALWAYS.
foreground:
        li $v1,-1
fg_tag:
        beq $a0,$a1,fg_return
        nop
        ld $t0,0($a0)
        ld $t1,8($a0)
        andi $t2,$t0,0x7fff           # GIFtag NLOOP
        dsrl $t3,$t0,60              # NREG (zero means sixteen)
        bnez $t3,1f
        nop
        li $t3,16
1:      dsrl $t4,$t0,58
        andi $t4,$t4,3
        sltiu $t5,$t4,2
        beqz $t5,fg_image
        addiu $a0,$a0,16
        multu $t2,$t3
        mflo $t2
        beqz $t4,fg_packed
        nop
        addiu $t2,$t2,1              # REGLIST pads to a qword
        srl $t2,$t2,1
fg_image:
        sll $t2,$t2,4
        b fg_next
        addu $t6,$a0,$t2
fg_packed:
        sll $t2,$t2,4
        addu $t6,$a0,$t2
        sltu $t7,$a1,$t6
        bnez $t7,fg_return
        li $t7,14                    # packed A+D is one register per GIFtag
        bne $t1,$t7,fg_next
        li $t7,1
        bne $t3,$t7,fg_next
        nop
fg_ad:
        beq $a0,$t6,fg_next
        nop
        ld $t7,8($a0)
        li $t8,0x47                  # TEST_1
        bne $t7,$t8,fg_ad_next
        nop
        lw $t7,0($a0)
        move $v1,$t7
        li $t8,0xfff9ffff
        and $t7,$t7,$t8
        lui $t8,2
        or $t7,$t7,$t8
        sw $t7,0($a0)
fg_ad_next:
        b fg_ad
        addiu $a0,$a0,16
fg_next:
        sltu $t7,$t6,$a1
        bnez $t7,fg_tag
        move $a0,$t6
fg_return:
        bltz $v1,1f
        move $v0,$a1
        li $t0,0x1000
        dsll $t0,$t0,48
        ori $t0,$t0,0x8001
        sd $t0,0($v0)
        li $t0,14
        sd $t0,8($v0)
        sd $v1,16($v0)                # restore the native final TEST_1 for later passes
        li $t0,0x47
        sd $t0,24($v0)
        addiu $v0,$v0,32
1:      jr $ra
        nop

# The Report component supplies its own frame, font style and key legend.
# Only this menu needs a taller frame and seven fixed label/value baselines.
report_frame:
        lbu $k0,settings+18
        beqz $k0,1f
        nop
        # Trim one 12-unit row above the first label; keep the lower edge anchored.
        addiu $a3,$a3,12
        li $t2,92
1:      j FRAME_DRAW
        nop
refresh:
        la $a1,template_sc
        menu_language $t0
        beqz $t0,1f
        nop
        la $a1,template_tc
1:      la $a2,attr
.if SP_EDITION
        lw $t9,lang_imports+4
        jr $t9
.else
        j LANG_SET
.endif
        nop
report_text:
        lbu $k0,settings+18
        beqz $k0,stock_text
        nop
        lbu $k0,0($a0)
        li $k1,0x82
        beq $k0,$k1,draw_rows
        nop
        # The native text parser supplies the footer as the second line.
        j TEXT_DRAW
        addiu $a2,$s7,88
draw_rows:
        addiu $sp,$sp,-64
        sd $ra,0($sp)
        sd $a2,8($sp)
        sd $t0,16($sp)
        sw $zero,24($sp)
        la $k1,words_sc
        menu_language $t2
        beqz $t2,1f
        nop
        la $k1,words_tc
1:      sw $k1,28($sp)
row_loop:
        lw $k0,24($sp)
        ld $a2,8($sp)
        ld $t0,16($sp)
        lbu $t2,settings+16
        bne $k0,$t2,label_text
        nop
        la $a0,arrow
        jal TEXT_DRAW
        li $a1,-113
        move $a3,$v0
label_text:
        lw $k0,24($sp)
        lw $k1,28($sp)
        sll $t2,$k0,2
        addu $t2,$t2,$k1
        lw $a0,0($t2)
        li $a1,-82
        ld $a2,8($sp)
        ld $t0,16($sp)
        jal TEXT_DRAW
        move $t1,$zero
        lw $k0,24($sp)
        la $t2,settings+8
        addu $t2,$t2,$k0
        lbu $t2,0($t2)
        la $k1,value_offsets
        addu $k1,$k1,$k0
        lbu $k0,0($k1)
        addu $t2,$t2,$k0
        lw $k1,28($sp)
        sll $t2,$t2,2
        addu $k1,$k1,$t2
        lw $a0,0($k1)
        li $a1,32
        ld $a2,8($sp)
        move $a3,$v0
        ld $t0,16($sp)
        move $t1,$zero
        jal TEXT_DRAW
        nop
        move $a3,$v0
        lw $k0,24($sp)
        addiu $k0,$k0,1
        sw $k0,24($sp)
        ld $t2,8($sp)
        addiu $t2,$t2,12
        sd $t2,8($sp)
        sltiu $k1,$k0,7
        bnez $k1,row_loop
        nop
        ld $ra,0($sp)
        jr $ra
        addiu $sp,$sp,64
stock_text:
        j STOCK_TEXT
        nop

.include "effects.inc"
.align 3
settings:
applied: .space 8
         .space 20
value_offsets: .byte 7,9,13,15,17,19,21
attr:    .byte 2,2,255,5,5,5,5
arrow:   .byte 0x81,0xcb,0
.include "cheat_text.inc"
