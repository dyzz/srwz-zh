; constructor_vtable_store 00311f50..00311f84
00311f50 27bdff60 addiu $sp, $sp, -0xa0
00311f54 0000282d move $a1, $zero
00311f58 ffbf0020 sd $ra, 0x20($sp)
00311f5c 7fb10010 sq $s1, 16($sp)
00311f60 0080882d move $s1, $a0
00311f64 0c0b2254 jal 0x2c8950
00311f68 7fb00000 sq $s0, 0($sp)
00311f6c 3c03004c lui $v1, 0x4c
00311f70 3c01005e lui $at, 0x5e
00311f74 24637ae0 addiu $v1, $v1, 0x7ae0
00311f78 24020001 addiu $v0, $zero, 1
00311f7c ae230000 sw $v1, ($s1)
00311f80 9023bb2e lbu $v1, -0x44d2($at)
; nonblank_validation_and_indirect_dispatch 002cb770..002cb878
002cb770 00118c3c dsll32 $s1, $s1, 0x10
002cb774 00118c3f dsra32 $s1, $s1, 0x10
002cb778 64160001 daddiu $s6, $zero, 1
002cb77c 0011082a slt $at, $zero, $s1
002cb780 10200033 beqz $at, 0x2cb850
002cb784 0000a82d move $s5, $zero
002cb788 0200902d move $s2, $s0
002cb78c 00000000 nop 
002cb790 8e420050 lw $v0, 0x50($s2)
002cb794 1040002e beqz $v0, 0x2cb850
002cb798 24540008 addiu $s4, $v0, 8
002cb79c 0000982d move $s3, $zero
002cb7a0 0c0694d4 jal 0x1a5350
002cb7a4 0280202d move $a0, $s4
002cb7a8 00021042 srl $v0, $v0, 1
002cb7ac 00022c3c dsll32 $a1, $v0, 0x10
002cb7b0 00052c3f dsra32 $a1, $a1, 0x10
002cb7b4 0005082a slt $at, $zero, $a1
002cb7b8 10200015 beqz $at, 0x2cb810
002cb7bc 0000302d move $a2, $zero
002cb7c0 34038140 ori $v1, $zero, 0x8140
002cb7c4 00000000 nop 
002cb7c8 82820000 lb $v0, ($s4)
002cb7cc 10400010 beqz $v0, 0x2cb810
002cb7d0 00022200 sll $a0, $v0, 8
002cb7d4 92820001 lbu $v0, 1($s4)
002cb7d8 3084ff00 andi $a0, $a0, 0xff00
002cb7dc 00821025 or $v0, $a0, $v0
002cb7e0 3042ffff andi $v0, $v0, 0xffff
002cb7e4 14430004 bne $v0, $v1, 0x2cb7f8
002cb7e8 26620001 addiu $v0, $s3, 1
002cb7ec 00029c3c dsll32 $s3, $v0, 0x10
002cb7f0 00139c3f dsra32 $s3, $s3, 0x10
002cb7f4 00000000 nop 
002cb7f8 24c20001 addiu $v0, $a2, 1
002cb7fc 0002343c dsll32 $a2, $v0, 0x10
002cb800 0006343f dsra32 $a2, $a2, 0x10
002cb804 00c5102a slt $v0, $a2, $a1
002cb808 1440ffef bnez $v0, 0x2cb7c8
002cb80c 26940002 addiu $s4, $s4, 2
002cb810 0013143c dsll32 $v0, $s3, 0x10
002cb814 0002143f dsra32 $v0, $v0, 0x10
002cb818 32c300ff andi $v1, $s6, 0xff
002cb81c 0045102a slt $v0, $v0, $a1
002cb820 26520004 addiu $s2, $s2, 4
002cb824 38420001 xori $v0, $v0, 1
002cb828 38420001 xori $v0, $v0, 1
002cb82c 304400ff andi $a0, $v0, 0xff
002cb830 26a20001 addiu $v0, $s5, 1
002cb834 00641824 and $v1, $v1, $a0
002cb838 0002ac3c dsll32 $s5, $v0, 0x10
002cb83c 0015ac3f dsra32 $s5, $s5, 0x10
002cb840 02b1102a slt $v0, $s5, $s1
002cb844 1440ffd2 bnez $v0, 0x2cb790
002cb848 0003b02b sltu $s6, $zero, $v1
002cb84c 00000000 nop 
002cb850 12c00007 beqz $s6, 0x2cb870
002cb854 00000000 nop 
002cb858 8e190000 lw $t9, ($s0)
002cb85c 8f390098 lw $t9, 0x98($t9)
002cb860 0320f809 jalr $t9
002cb864 0200202d move $a0, $s0
002cb868 100001a9 b 0x2cbf10
002cb86c 00000000 nop 
002cb870 100001a7 b 0x2cbf10
002cb874 24170006 addiu $s7, $zero, 6
