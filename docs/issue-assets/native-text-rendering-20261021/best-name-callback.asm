; constructor_vtable_store 0030bdd0..0030be04
0030bdd0 27bdff60 addiu $sp, $sp, -0xa0
0030bdd4 0000282d move $a1, $zero
0030bdd8 ffbf0020 sd $ra, 0x20($sp)
0030bddc 7fb10010 sq $s1, 16($sp)
0030bde0 0080882d move $s1, $a0
0030bde4 0c0b0724 jal 0x2c1c90
0030bde8 7fb00000 sq $s0, 0($sp)
0030bdec 3c030045 lui $v1, 0x45
0030bdf0 3c010056 lui $at, 0x56
0030bdf4 24639c70 addiu $v1, $v1, -0x6390
0030bdf8 24020001 addiu $v0, $zero, 1
0030bdfc ae230000 sw $v1, ($s1)
0030be00 90238d6e lbu $v1, -0x7292($at)
; nonblank_validation_and_indirect_dispatch 002c4ab0..002c4bb8
002c4ab0 00118c3c dsll32 $s1, $s1, 0x10
002c4ab4 00118c3f dsra32 $s1, $s1, 0x10
002c4ab8 64160001 daddiu $s6, $zero, 1
002c4abc 0011082a slt $at, $zero, $s1
002c4ac0 10200033 beqz $at, 0x2c4b90
002c4ac4 0000a82d move $s5, $zero
002c4ac8 0200902d move $s2, $s0
002c4acc 00000000 nop 
002c4ad0 8e420050 lw $v0, 0x50($s2)
002c4ad4 1040002e beqz $v0, 0x2c4b90
002c4ad8 24540008 addiu $s4, $v0, 8
002c4adc 0000982d move $s3, $zero
002c4ae0 0c068490 jal 0x1a1240
002c4ae4 0280202d move $a0, $s4
002c4ae8 00021042 srl $v0, $v0, 1
002c4aec 00022c3c dsll32 $a1, $v0, 0x10
002c4af0 00052c3f dsra32 $a1, $a1, 0x10
002c4af4 0005082a slt $at, $zero, $a1
002c4af8 10200015 beqz $at, 0x2c4b50
002c4afc 0000302d move $a2, $zero
002c4b00 34038140 ori $v1, $zero, 0x8140
002c4b04 00000000 nop 
002c4b08 82820000 lb $v0, ($s4)
002c4b0c 10400010 beqz $v0, 0x2c4b50
002c4b10 00022200 sll $a0, $v0, 8
002c4b14 92820001 lbu $v0, 1($s4)
002c4b18 3084ff00 andi $a0, $a0, 0xff00
002c4b1c 00821025 or $v0, $a0, $v0
002c4b20 3042ffff andi $v0, $v0, 0xffff
002c4b24 14430004 bne $v0, $v1, 0x2c4b38
002c4b28 26620001 addiu $v0, $s3, 1
002c4b2c 00029c3c dsll32 $s3, $v0, 0x10
002c4b30 00139c3f dsra32 $s3, $s3, 0x10
002c4b34 00000000 nop 
002c4b38 24c20001 addiu $v0, $a2, 1
002c4b3c 0002343c dsll32 $a2, $v0, 0x10
002c4b40 0006343f dsra32 $a2, $a2, 0x10
002c4b44 00c5102a slt $v0, $a2, $a1
002c4b48 1440ffef bnez $v0, 0x2c4b08
002c4b4c 26940002 addiu $s4, $s4, 2
002c4b50 0013143c dsll32 $v0, $s3, 0x10
002c4b54 0002143f dsra32 $v0, $v0, 0x10
002c4b58 32c300ff andi $v1, $s6, 0xff
002c4b5c 0045102a slt $v0, $v0, $a1
002c4b60 26520004 addiu $s2, $s2, 4
002c4b64 38420001 xori $v0, $v0, 1
002c4b68 38420001 xori $v0, $v0, 1
002c4b6c 304400ff andi $a0, $v0, 0xff
002c4b70 26a20001 addiu $v0, $s5, 1
002c4b74 00641824 and $v1, $v1, $a0
002c4b78 0002ac3c dsll32 $s5, $v0, 0x10
002c4b7c 0015ac3f dsra32 $s5, $s5, 0x10
002c4b80 02b1102a slt $v0, $s5, $s1
002c4b84 1440ffd2 bnez $v0, 0x2c4ad0
002c4b88 0003b02b sltu $s6, $zero, $v1
002c4b8c 00000000 nop 
002c4b90 12c00007 beqz $s6, 0x2c4bb0
002c4b94 00000000 nop 
002c4b98 8e190000 lw $t9, ($s0)
002c4b9c 8f390098 lw $t9, 0x98($t9)
002c4ba0 0320f809 jalr $t9
002c4ba4 0200202d move $a0, $s0
002c4ba8 100001a9 b 0x2c5250
002c4bac 00000000 nop 
002c4bb0 100001a7 b 0x2c5250
002c4bb4 24170006 addiu $s7, $zero, 6
