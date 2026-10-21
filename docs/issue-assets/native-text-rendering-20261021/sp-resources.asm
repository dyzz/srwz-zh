
; resource_initialize 0013aa00..0013ad00
0013aa00 27bdff00 addiu $sp, $sp, -0x100
0013aa04 3c02004f lui $v0, 0x4f
0013aa08 ffbf0020 sd $ra, 0x20($sp)
0013aa0c 3c060045 lui $a2, 0x45
0013aa10 7fb10010 sq $s1, 16($sp)
0013aa14 3c010045 lui $at, 0x45
0013aa18 7fb00000 sq $s0, 0($sp)
0013aa1c 2442d1a0 addiu $v0, $v0, -0x2e60
0013aa20 84232dea lh $v1, 0x2dea($at)
0013aa24 24c62e10 addiu $a2, $a2, 0x2e10
0013aa28 a7808574 sh $zero, -0x7a8c($gp)
0013aa2c 27a700f8 addiu $a3, $sp, 0xf8
0013aa30 0000402d move $t0, $zero
0013aa34 3c01004f lui $at, 0x4f
0013aa38 00031880 sll $v1, $v1, 2
0013aa3c ac22d5a0 sw $v0, -0x2a60($at)
0013aa40 00c31821 addu $v1, $a2, $v1
0013aa44 3c010045 lui $at, 0x45
0013aa48 8c650000 lw $a1, ($v1)
0013aa4c 84222dec lh $v0, 0x2dec($at)
0013aa50 00021080 sll $v0, $v0, 2
0013aa54 3c01004f lui $at, 0x4f
0013aa58 00c21021 addu $v0, $a2, $v0
0013aa5c 8c241938 lw $a0, 0x1938($at)
0013aa60 8c420000 lw $v0, ($v0)
0013aa64 0c04e810 jal 0x13a040
0013aa68 00453023 subu $a2, $v0, $a1
0013aa6c 0c0400f4 jal 0x1003d0
0013aa70 3c040001 lui $a0, 1
0013aa74 27b000fc addiu $s0, $sp, 0xfc
0013aa78 0040882d move $s1, $v0
0013aa7c 8e040000 lw $a0, ($s0)
0013aa80 0c072848 jal 0x1ca120
0013aa84 0220282d move $a1, $s1
0013aa88 24070002 addiu $a3, $zero, 2
0013aa8c 27a40090 addiu $a0, $sp, 0x90
0013aa90 24052ca9 addiu $a1, $zero, 0x2ca9
0013aa94 24060001 addiu $a2, $zero, 1
0013aa98 0000402d move $t0, $zero
0013aa9c 0000482d move $t1, $zero
0013aaa0 240a0010 addiu $t2, $zero, 0x10
0013aaa4 0c043540 jal 0x10d500
0013aaa8 00e0582d move $t3, $a3
0013aaac 0c046c98 jal 0x11b260
0013aab0 0000202d move $a0, $zero
0013aab4 27a40090 addiu $a0, $sp, 0x90
0013aab8 0c04360a jal 0x10d828
0013aabc 0220282d move $a1, $s1
0013aac0 0000202d move $a0, $zero
0013aac4 0c04347a jal 0x10d1e8
0013aac8 0000282d move $a1, $zero
0013aacc 240a0100 addiu $t2, $zero, 0x100
0013aad0 27a40030 addiu $a0, $sp, 0x30
0013aad4 24052caa addiu $a1, $zero, 0x2caa
0013aad8 24060004 addiu $a2, $zero, 4
0013aadc 24070014 addiu $a3, $zero, 0x14
0013aae0 0000402d move $t0, $zero
0013aae4 0000482d move $t1, $zero
0013aae8 0c043540 jal 0x10d500
0013aaec 0140582d move $t3, $t2
0013aaf0 0c046c98 jal 0x11b260
0013aaf4 0000202d move $a0, $zero
0013aaf8 27a40030 addiu $a0, $sp, 0x30
0013aafc 0c04360a jal 0x10d828
0013ab00 26250040 addiu $a1, $s1, 0x40
0013ab04 0000202d move $a0, $zero
0013ab08 0c04347a jal 0x10d1e8
0013ab0c 0000282d move $a1, $zero
0013ab10 0c040110 jal 0x100440
0013ab14 0220202d move $a0, $s1
0013ab18 0c04e8e4 jal 0x13a390
0013ab1c 27a400f8 addiu $a0, $sp, 0xf8
0013ab20 3c01004f lui $at, 0x4f
0013ab24 24020800 addiu $v0, $zero, 0x800
0013ab28 a420d5b0 sh $zero, -0x2a50($at)
0013ab2c 24040010 addiu $a0, $zero, 0x10
0013ab30 3c01004f lui $at, 0x4f
0013ab34 24052800 addiu $a1, $zero, 0x2800
0013ab38 a420d5b2 sh $zero, -0x2a4e($at)
0013ab3c 3c01004f lui $at, 0x4f
0013ab40 a422d5b4 sh $v0, -0x2a4c($at)
0013ab44 3c01004f lui $at, 0x4f
0013ab48 a422d5b6 sh $v0, -0x2a4a($at)
0013ab4c 3c01004f lui $at, 0x4f
0013ab50 a420d5ba sh $zero, -0x2a46($at)
0013ab54 3c01004f lui $at, 0x4f
0013ab58 a420d5b8 sh $zero, -0x2a48($at)
0013ab5c 3c01004f lui $at, 0x4f
0013ab60 a420d5c2 sh $zero, -0x2a3e($at)
0013ab64 3c01004f lui $at, 0x4f
0013ab68 0c068542 jal 0x1a1508
0013ab6c a420d5c0 sh $zero, -0x2a40($at)
0013ab70 3c01004f lui $at, 0x4f
0013ab74 24040010 addiu $a0, $zero, 0x10
0013ab78 ac22d608 sw $v0, -0x29f8($at)
0013ab7c 0c068542 jal 0x1a1508
0013ab80 24052000 addiu $a1, $zero, 0x2000
0013ab84 3c01004f lui $at, 0x4f
0013ab88 24040080 addiu $a0, $zero, 0x80
0013ab8c ac22d610 sw $v0, -0x29f0($at)
0013ab90 3c020001 lui $v0, 1
0013ab94 0c068542 jal 0x1a1508
0013ab98 3445e000 ori $a1, $v0, 0xe000
0013ab9c 3c01004f lui $at, 0x4f
0013aba0 0000282d move $a1, $zero
0013aba4 ac22d630 sw $v0, -0x29d0($at)
0013aba8 3c030001 lui $v1, 1
0013abac 3464e000 ori $a0, $v1, 0xe000
0013abb0 a0400000 sb $zero, ($v0)
0013abb4 a0400001 sb $zero, 1($v0)
0013abb8 24a50008 addiu $a1, $a1, 8
0013abbc 24420002 addiu $v0, $v0, 2
0013abc0 00a4182a slt $v1, $a1, $a0
0013abc4 a0400000 sb $zero, ($v0)
0013abc8 a0400001 sb $zero, 1($v0)
0013abcc 24420002 addiu $v0, $v0, 2
0013abd0 a0400000 sb $zero, ($v0)
0013abd4 a0400001 sb $zero, 1($v0)
0013abd8 24420002 addiu $v0, $v0, 2
0013abdc a0400000 sb $zero, ($v0)
0013abe0 a0400001 sb $zero, 1($v0)
0013abe4 1460fff2 bnez $v1, 0x13abb0
0013abe8 24420002 addiu $v0, $v0, 2
0013abec 3c010045 lui $at, 0x45
0013abf0 8c2524e8 lw $a1, 0x24e8($at)
0013abf4 0c068542 jal 0x1a1508
0013abf8 24040010 addiu $a0, $zero, 0x10
0013abfc 3c01004f lui $at, 0x4f
0013ac00 3c050045 lui $a1, 0x45
0013ac04 ac22d628 sw $v0, -0x29d8($at)
0013ac08 24a52e10 addiu $a1, $a1, 0x2e10
0013ac0c 3c010045 lui $at, 0x45
0013ac10 27a700f8 addiu $a3, $sp, 0xf8
0013ac14 84232de4 lh $v1, 0x2de4($at)
0013ac18 0000402d move $t0, $zero
0013ac1c 3c010045 lui $at, 0x45
0013ac20 00031880 sll $v1, $v1, 2
0013ac24 84222de6 lh $v0, 0x2de6($at)
0013ac28 00a31821 addu $v1, $a1, $v1
0013ac2c 00021080 sll $v0, $v0, 2
0013ac30 3c01004f lui $at, 0x4f
0013ac34 00a21021 addu $v0, $a1, $v0
0013ac38 8c241938 lw $a0, 0x1938($at)
0013ac3c 8c650000 lw $a1, ($v1)
0013ac40 8c420000 lw $v0, ($v0)
0013ac44 0c04e810 jal 0x13a040
0013ac48 00453023 subu $a2, $v0, $a1
0013ac4c 3c01004f lui $at, 0x4f
0013ac50 8c25d628 lw $a1, -0x29d8($at)
0013ac54 0c072848 jal 0x1ca120
0013ac58 8e040000 lw $a0, ($s0)
0013ac5c 0c04e8e4 jal 0x13a390
0013ac60 27a400f8 addiu $a0, $sp, 0xf8
0013ac64 24030010 addiu $v1, $zero, 0x10
0013ac68 3c01004f lui $at, 0x4f
0013ac6c a423d5c4 sh $v1, -0x2a3c($at)
0013ac70 24020001 addiu $v0, $zero, 1
0013ac74 3c01004f lui $at, 0x4f
0013ac78 0000282d move $a1, $zero
0013ac7c ac22d638 sw $v0, -0x29c8($at)
0013ac80 2406ffff addiu $a2, $zero, -1
0013ac84 3c010045 lui $at, 0x45
0013ac88 8c242888 lw $a0, 0x2888($at)
0013ac8c 0c04eb4c jal 0x13ad30
0013ac90 0000382d move $a3, $zero
0013ac94 3c01004f lui $at, 0x4f
0013ac98 a420d5bc sh $zero, -0x2a44($at)
0013ac9c 3c01004f lui $at, 0x4f
0013aca0 0c04f41c jal 0x13d070
0013aca4 a420d5be sh $zero, -0x2a42($at)
0013aca8 3c01004f lui $at, 0x4f
0013acac ac20d638 sw $zero, -0x29c8($at)
0013acb0 3c01004f lui $at, 0x4f
0013acb4 a420d5b0 sh $zero, -0x2a50($at)
0013acb8 3c01004f lui $at, 0x4f
0013acbc 8423d5b8 lh $v1, -0x2a48($at)
0013acc0 3c01004f lui $at, 0x4f
0013acc4 8422d5ba lh $v0, -0x2a46($at)
0013acc8 3c01004f lui $at, 0x4f
0013accc a423d5bc sh $v1, -0x2a44($at)
0013acd0 3c01004f lui $at, 0x4f
0013acd4 0c04e8e8 jal 0x13a3a0
0013acd8 a422d5be sh $v0, -0x2a42($at)
0013acdc 0c04ea68 jal 0x13a9a0
0013ace0 00000000 nop 
0013ace4 dfbf0020 ld $ra, 0x20($sp)
0013ace8 7bb10010 lq $s1, 16($sp)
0013acec 7bb00000 lq $s0, 0($sp)
0013acf0 03e00008 jr $ra
0013acf4 27bd0100 addiu $sp, $sp, 0x100
0013acf8 00000000 nop 
0013acfc 00000000 nop 

; atlas_reset_to_reserved 0013ad00..0013ad30
0013ad00 3c01004f lui $at, 0x4f
0013ad04 8424d5bc lh $a0, -0x2a44($at)
0013ad08 3c01004f lui $at, 0x4f
0013ad0c 8423d5be lh $v1, -0x2a42($at)
0013ad10 3c01004f lui $at, 0x4f
0013ad14 a424d5b8 sh $a0, -0x2a48($at)
0013ad18 3c01004f lui $at, 0x4f
0013ad1c 03e00008 jr $ra
0013ad20 a423d5ba sh $v1, -0x2a46($at)
0013ad24 00000000 nop 
0013ad28 00000000 nop 
0013ad2c 00000000 nop 

; frame_clear 0013ce40..0013ce90
0013ce40 00041e3c dsll32 $v1, $a0, 0x18
0013ce44 27bdfff0 addiu $sp, $sp, -0x10
0013ce48 00031e3f dsra32 $v1, $v1, 0x18
0013ce4c 1060000c beqz $v1, 0x13ce80
0013ce50 ffbf0000 sd $ra, ($sp)
0013ce54 3c01004f lui $at, 0x4f
0013ce58 a420d5b0 sh $zero, -0x2a50($at)
0013ce5c 3c01004f lui $at, 0x4f
0013ce60 0c04eb40 jal 0x13ad00
0013ce64 a420d5b2 sh $zero, -0x2a4e($at)
0013ce68 3c03004f lui $v1, 0x4f
0013ce6c 3c01004f lui $at, 0x4f
0013ce70 2463d1a0 addiu $v1, $v1, -0x2e60
0013ce74 a7808574 sh $zero, -0x7a8c($gp)
0013ce78 ac23d5a0 sw $v1, -0x2a60($at)
0013ce7c 00000000 nop 
0013ce80 dfbf0000 ld $ra, ($sp)
0013ce84 03e00008 jr $ra
0013ce88 27bd0010 addiu $sp, $sp, 0x10
0013ce8c 00000000 nop 

; font_reset_wrapper 0013ce90..0013cec0
0013ce90 27bdfff0 addiu $sp, $sp, -0x10
0013ce94 ffbf0000 sd $ra, ($sp)
0013ce98 0c04e8e8 jal 0x13a3a0
0013ce9c 00000000 nop 
0013cea0 0c04f390 jal 0x13ce40
0013cea4 0000202d move $a0, $zero
0013cea8 dfbf0000 ld $ra, ($sp)
0013ceac 03e00008 jr $ra
0013ceb0 27bd0010 addiu $sp, $sp, 0x10
0013ceb4 00000000 nop 
0013ceb8 00000000 nop 
0013cebc 00000000 nop 

; scatter 0013d070..0013d160
0013d070 3c01004f lui $at, 0x4f
0013d074 3c07004f lui $a3, 0x4f
0013d078 8425d5bc lh $a1, -0x2a44($at)
0013d07c 24e7d1a0 addiu $a3, $a3, -0x2e60
0013d080 3c01004f lui $at, 0x4f
0013d084 8424d5be lh $a0, -0x2a42($at)
0013d088 1000002f b 0x13d148
0013d08c 0000182d move $v1, $zero
0013d090 3c01004f lui $at, 0x4f
0013d094 8c2ad628 lw $t2, -0x29d8($at)
0013d098 0004343c dsll32 $a2, $a0, 0x10
0013d09c 94ec0000 lhu $t4, ($a3)
0013d0a0 0006343f dsra32 $a2, $a2, 0x10
0013d0a4 00064a00 sll $t1, $a2, 8
0013d0a8 0005343c dsll32 $a2, $a1, 0x10
0013d0ac 0006343f dsra32 $a2, $a2, 0x10
0013d0b0 00063043 sra $a2, $a2, 1
0013d0b4 3c01004f lui $at, 0x4f
0013d0b8 8c28d630 lw $t0, -0x29d0($at)
0013d0bc 000c58c0 sll $t3, $t4, 3
0013d0c0 016c5821 addu $t3, $t3, $t4
0013d0c4 01094021 addu $t0, $t0, $t1
0013d0c8 000b4940 sll $t1, $t3, 5
0013d0cc 01496021 addu $t4, $t2, $t1
0013d0d0 01065821 addu $t3, $t0, $a2
0013d0d4 20060018 addi $a2, $zero, 0x18
0013d0d8 8d880000 lw $t0, ($t4)
0013d0dc 8d890004 lw $t1, 4($t4)
0013d0e0 8d8a0008 lw $t2, 8($t4)
0013d0e4 ad680000 sw $t0, ($t3)
0013d0e8 ad690004 sw $t1, 4($t3)
0013d0ec ad6a0008 sw $t2, 8($t3)
0013d0f0 218c000c addi $t4, $t4, 0xc
0013d0f4 216b0100 addi $t3, $t3, 0x100
0013d0f8 20c6ffff addi $a2, $a2, -1
0013d0fc 14c0fff6 bnez $a2, 0x13d0d8
0013d100 00000000 nop 
0013d104 24a60018 addiu $a2, $a1, 0x18
0013d108 24e70002 addiu $a3, $a3, 2
0013d10c 00062c3c dsll32 $a1, $a2, 0x10
0013d110 0006343c dsll32 $a2, $a2, 0x10
0013d114 0006343f dsra32 $a2, $a2, 0x10
0013d118 0006343c dsll32 $a2, $a2, 0x10
0013d11c 0006343f dsra32 $a2, $a2, 0x10
0013d120 28c601f8 slti $a2, $a2, 0x1f8
0013d124 14c00006 bnez $a2, 0x13d140
0013d128 00052c3f dsra32 $a1, $a1, 0x10
0013d12c 24840018 addiu $a0, $a0, 0x18
0013d130 0000282d move $a1, $zero
0013d134 0004243c dsll32 $a0, $a0, 0x10
0013d138 0004243f dsra32 $a0, $a0, 0x10
0013d13c 00000000 nop 
0013d140 24630001 addiu $v1, $v1, 1
0013d144 00000000 nop 
0013d148 97868574 lhu $a2, -0x7a8c($gp)
0013d14c 0066302a slt $a2, $v1, $a2
0013d150 14c0ffcf bnez $a2, 0x13d090
0013d154 00000000 nop 
0013d158 03e00008 jr $ra
0013d15c 00000000 nop 

; default_palette_upload 0013a9a0..0013aa00
0013a9a0 27bdff90 addiu $sp, $sp, -0x70
0013a9a4 240a0010 addiu $t2, $zero, 0x10
0013a9a8 ffbf0000 sd $ra, ($sp)
0013a9ac 27a40010 addiu $a0, $sp, 0x10
0013a9b0 24052680 addiu $a1, $zero, 0x2680
0013a9b4 24060001 addiu $a2, $zero, 1
0013a9b8 0000382d move $a3, $zero
0013a9bc 0000402d move $t0, $zero
0013a9c0 0000482d move $t1, $zero
0013a9c4 0c043540 jal 0x10d500
0013a9c8 0140582d move $t3, $t2
0013a9cc 0c046c98 jal 0x11b260
0013a9d0 0000202d move $a0, $zero
0013a9d4 3c050045 lui $a1, 0x45
0013a9d8 27a40010 addiu $a0, $sp, 0x10
0013a9dc 0c04360a jal 0x10d828
0013a9e0 24a52890 addiu $a1, $a1, 0x2890
0013a9e4 0000202d move $a0, $zero
0013a9e8 0c04347a jal 0x10d1e8
0013a9ec 0000282d move $a1, $zero
0013a9f0 dfbf0000 ld $ra, ($sp)
0013a9f4 03e00008 jr $ra
0013a9f8 27bd0070 addiu $sp, $sp, 0x70
0013a9fc 00000000 nop 
