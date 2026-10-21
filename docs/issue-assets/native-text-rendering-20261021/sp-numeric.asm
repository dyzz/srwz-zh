
; unsigned_number 0013c800..0013caa0
0013c800 27bdffc0 addiu $sp, $sp, -0x40
0013c804 ffbf0030 sd $ra, 0x30($sp)
0013c808 7fb20020 sq $s2, 32($sp)
0013c80c 7fb10010 sq $s1, 16($sp)
0013c810 11000007 beqz $t0, 0x13c830
0013c814 7fb00000 sq $s0, 0($sp)
0013c818 3c01004f lui $at, 0x4f
0013c81c 8c32d610 lw $s2, -0x29f0($at)
0013c820 3c01004f lui $at, 0x4f
0013c824 8431d5b0 lh $s1, -0x2a50($at)
0013c828 3c01004f lui $at, 0x4f
0013c82c 8430d5b2 lh $s0, -0x2a4e($at)
0013c830 2402ffff addiu $v0, $zero, -1
0013c834 11220002 beq $t1, $v0, 0x13c840
0013c838 3c01004f lui $at, 0x4f
0013c83c ac29d5e4 sw $t1, -0x2a1c($at)
0013c840 28810002 slti $at, $a0, 2
0013c844 14200010 bnez $at, 0x13c888
0013c848 240b0001 addiu $t3, $zero, 1
0013c84c 3c090045 lui $t1, 0x45
0013c850 0004183c dsll32 $v1, $a0, 0
0013c854 25292d68 addiu $t1, $t1, 0x2d68
0013c858 0003183f dsra32 $v1, $v1, 0
0013c85c 00000000 nop 
0013c860 dd220000 ld $v0, ($t1)
0013c864 0062102a slt $v0, $v1, $v0
0013c868 14400005 bnez $v0, 0x13c880
0013c86c 00000000 nop 
0013c870 25290008 addiu $t1, $t1, 8
0013c874 1000fffa b 0x13c860
0013c878 256b0001 addiu $t3, $t3, 1
0013c87c 00000000 nop 
0013c880 256bffff addiu $t3, $t3, -1
0013c884 00000000 nop 
0013c888 3c01004f lui $at, 0x4f
0013c88c 9423d5b2 lhu $v1, -0x2a4e($at)
0013c890 3c020045 lui $v0, 0x45
0013c894 000b48c0 sll $t1, $t3, 3
0013c898 24422d60 addiu $v0, $v0, 0x2d60
0013c89c 00494821 addu $t1, $v0, $t1
0013c8a0 8d290000 lw $t1, ($t1)
0013c8a4 3c01004f lui $at, 0x4f
0013c8a8 00031940 sll $v1, $v1, 5
0013c8ac 8c22d610 lw $v0, -0x29f0($at)
0013c8b0 10e0000d beqz $a3, 0x13c8e8
0013c8b4 00431821 addu $v1, $v0, $v1
0013c8b8 3c01004f lui $at, 0x4f
0013c8bc 842cd5e0 lh $t4, -0x2a20($at)
0013c8c0 3c01004f lui $at, 0x4f
0013c8c4 8427d5dc lh $a3, -0x2a24($at)
0013c8c8 016c1018 mult $v0, $t3, $t4
0013c8cc 00e21021 addu $v0, $a3, $v0
0013c8d0 004c1023 subu $v0, $v0, $t4
0013c8d4 0002143c dsll32 $v0, $v0, 0x10
0013c8d8 0002143f dsra32 $v0, $v0, 0x10
0013c8dc 00a21023 subu $v0, $a1, $v0
0013c8e0 00022c3c dsll32 $a1, $v0, 0x10
0013c8e4 00052c3f dsra32 $a1, $a1, 0x10
0013c8e8 3c01004f lui $at, 0x4f
0013c8ec a425d61a sh $a1, -0x29e6($at)
0013c8f0 000b082a slt $at, $zero, $t3
0013c8f4 10200046 beqz $at, 0x13ca10
0013c8f8 0000602d move $t4, $zero
0013c8fc 3c076666 lui $a3, 0x6666
0013c900 24020024 addiu $v0, $zero, 0x24
0013c904 34ee6667 ori $t6, $a3, 0x6667
0013c908 241800ff addiu $t8, $zero, 0xff
0013c90c 00000000 nop 
0013c910 a4650004 sh $a1, 4($v1)
0013c914 0089001a div $zero, $a0, $t1
0013c918 a4660006 sh $a2, 6($v1)
0013c91c 3c01004f lui $at, 0x4f
0013c920 8c2dd5e4 lw $t5, -0x2a1c($at)
0013c924 ac6d0008 sw $t5, 8($v1)
0013c928 3c01004f lui $at, 0x4f
0013c92c 00003812 mflo $a3
0013c930 24ef0001 addiu $t7, $a3, 1
0013c934 000f6840 sll $t5, $t7, 1
0013c938 01af6821 addu $t5, $t5, $t7
0013c93c 000d68c0 sll $t5, $t5, 3
0013c940 a46d0000 sh $t5, ($v1)
0013c944 a4600002 sh $zero, 2($v1)
0013c948 842dd5dc lh $t5, -0x2a24($at)
0013c94c a06d000c sb $t5, 0xc($v1)
0013c950 3c01004f lui $at, 0x4f
0013c954 842dd5de lh $t5, -0x2a22($at)
0013c958 a06d000d sb $t5, 0xd($v1)
0013c95c 3c01004f lui $at, 0x4f
0013c960 842dd5e2 lh $t5, -0x2a1e($at)
0013c964 a06d000e sb $t5, 0xe($v1)
0013c968 3c01004f lui $at, 0x4f
0013c96c a062000f sb $v0, 0xf($v1)
0013c970 902dd5fa lbu $t5, -0x2a06($at)
0013c974 a06d0010 sb $t5, 0x10($v1)
0013c978 3c01004f lui $at, 0x4f
0013c97c 8c2dd5d4 lw $t5, -0x2a2c($at)
0013c980 ac6d0014 sw $t5, 0x14($v1)
0013c984 3c01004f lui $at, 0x4f
0013c988 8c2dd5d8 lw $t5, -0x2a28($at)
0013c98c ac6d0018 sw $t5, 0x18($v1)
0013c990 3c01004f lui $at, 0x4f
0013c994 802dd600 lb $t5, -0x2a00($at)
0013c998 a06d001c sb $t5, 0x1c($v1)
0013c99c 3c01004f lui $at, 0x4f
0013c9a0 842fd5e0 lh $t7, -0x2a20($at)
0013c9a4 24630020 addiu $v1, $v1, 0x20
0013c9a8 3c01004f lui $at, 0x4f
0013c9ac 00af2821 addu $a1, $a1, $t7
0013c9b0 942dd5b2 lhu $t5, -0x2a4e($at)
0013c9b4 00052c3c dsll32 $a1, $a1, 0x10
0013c9b8 25ad0001 addiu $t5, $t5, 1
0013c9bc 3c01004f lui $at, 0x4f
0013c9c0 a42dd5b2 sh $t5, -0x2a4e($at)
0013c9c4 3c01004f lui $at, 0x4f
0013c9c8 942dd5b2 lhu $t5, -0x2a4e($at)
0013c9cc 15b80006 bne $t5, $t8, 0x13c9e8
0013c9d0 00052c3f dsra32 $a1, $a1, 0x10
0013c9d4 25adffff addiu $t5, $t5, -1
0013c9d8 3c01004f lui $at, 0x4f
0013c9dc 2463ffe0 addiu $v1, $v1, -0x20
0013c9e0 a42dd5b2 sh $t5, -0x2a4e($at)
0013c9e4 00000000 nop 
0013c9e8 00096fc2 srl $t5, $t1, 0x1f
0013c9ec 00e97818 mult $t7, $a3, $t1
0013c9f0 258c0001 addiu $t4, $t4, 1
0013c9f4 01c90018 mult $t6, $t1
0013c9f8 018b382a slt $a3, $t4, $t3
0013c9fc 008f2023 subu $a0, $a0, $t7
0013ca00 00004810 mfhi $t1
0013ca04 00094883 sra $t1, $t1, 2
0013ca08 14e0ffc1 bnez $a3, 0x13c910
0013ca0c 012d4821 addu $t1, $t1, $t5
0013ca10 3c01004f lui $at, 0x4f
0013ca14 11000018 beqz $t0, 0x13ca78
0013ca18 a425d618 sh $a1, -0x29e8($at)
0013ca1c 3c01004f lui $at, 0x4f
0013ca20 0010343c dsll32 $a2, $s0, 0x10
0013ca24 a420d5b0 sh $zero, -0x2a50($at)
0013ca28 0006343f dsra32 $a2, $a2, 0x10
0013ca2c 3c01004f lui $at, 0x4f
0013ca30 00061940 sll $v1, $a2, 5
0013ca34 9422d5b2 lhu $v0, -0x2a4e($at)
0013ca38 02431821 addu $v1, $s2, $v1
0013ca3c 0100202d move $a0, $t0
0013ca40 0140282d move $a1, $t2
0013ca44 3c01004f lui $at, 0x4f
0013ca48 00461023 subu $v0, $v0, $a2
0013ca4c ac23d610 sw $v1, -0x29f0($at)
0013ca50 3c01004f lui $at, 0x4f
0013ca54 0c04edd0 jal 0x13b740
0013ca58 a422d5b2 sh $v0, -0x2a4e($at)
0013ca5c 3c01004f lui $at, 0x4f
0013ca60 0040402d move $t0, $v0
0013ca64 ac32d610 sw $s2, -0x29f0($at)
0013ca68 3c01004f lui $at, 0x4f
0013ca6c a431d5b0 sh $s1, -0x2a50($at)
0013ca70 3c01004f lui $at, 0x4f
0013ca74 a430d5b2 sh $s0, -0x2a4e($at)
0013ca78 dfbf0030 ld $ra, 0x30($sp)
0013ca7c 7bb20020 lq $s2, 32($sp)
0013ca80 0100102d move $v0, $t0
0013ca84 7bb10010 lq $s1, 16($sp)
0013ca88 7bb00000 lq $s0, 0($sp)
0013ca8c 03e00008 jr $ra
0013ca90 27bd0040 addiu $sp, $sp, 0x40
0013ca94 00000000 nop 
0013ca98 00000000 nop 
0013ca9c 00000000 nop 

; signed_number 0013caa0..0013cc30
0013caa0 27bdff90 addiu $sp, $sp, -0x70
0013caa4 ffbf0060 sd $ra, 0x60($sp)
0013caa8 7fb50050 sq $s5, 80($sp)
0013caac 7fb40040 sq $s4, 64($sp)
0013cab0 00a0a82d move $s5, $a1
0013cab4 7fb30030 sq $s3, 48($sp)
0013cab8 00c0a02d move $s4, $a2
0013cabc 7fb20020 sq $s2, 32($sp)
0013cac0 00e0982d move $s3, $a3
0013cac4 7fb10010 sq $s1, 16($sp)
0013cac8 0120902d move $s2, $t1
0013cacc 7fb00000 sq $s0, 0($sp)
0013cad0 0080802d move $s0, $a0
0013cad4 06010048 bgez $s0, 0x13cbf8
0013cad8 0140882d move $s1, $t2
0013cadc 1660001a bnez $s3, 0x13cb48
0013cae0 00152c3c dsll32 $a1, $s5, 0x10
0013cae4 0014343c dsll32 $a2, $s4, 0x10
0013cae8 3c04004a lui $a0, 0x4a
0013caec 0100382d move $a3, $t0
0013caf0 00052c3f dsra32 $a1, $a1, 0x10
0013caf4 0006343f dsra32 $a2, $a2, 0x10
0013caf8 24847710 addiu $a0, $a0, 0x7710
0013cafc 0240402d move $t0, $s2
0013cb00 0c04f414 jal 0x13d050
0013cb04 0000482d move $t1, $zero
0013cb08 0040402d move $t0, $v0
0013cb0c 3c01004f lui $at, 0x4f
0013cb10 8422d5e0 lh $v0, -0x2a20($at)
0013cb14 00108023 negu $s0, $s0
0013cb18 0280302d move $a2, $s4
0013cb1c 0260382d move $a3, $s3
0013cb20 0240482d move $t1, $s2
0013cb24 0220502d move $t2, $s1
0013cb28 0200202d move $a0, $s0
0013cb2c 02a21021 addu $v0, $s5, $v0
0013cb30 0002ac3c dsll32 $s5, $v0, 0x10
0013cb34 0015ac3f dsra32 $s5, $s5, 0x10
0013cb38 0c04f200 jal 0x13c800
0013cb3c 02a0282d move $a1, $s5
0013cb40 1000002f b 0x13cc00
0013cb44 00000000 nop 
0013cb48 00108023 negu $s0, $s0
0013cb4c 0000502d move $t2, $zero
0013cb50 1200000d beqz $s0, 0x13cb88
0013cb54 0200282d move $a1, $s0
0013cb58 3c026666 lui $v0, 0x6666
0013cb5c 34446667 ori $a0, $v0, 0x6667
0013cb60 00051fc2 srl $v1, $a1, 0x1f
0013cb64 00850018 mult $a0, $a1
0013cb68 00000000 nop 
0013cb6c 00000000 nop 
0013cb70 00001010 mfhi $v0
0013cb74 00021083 sra $v0, $v0, 2
0013cb78 00432821 addu $a1, $v0, $v1
0013cb7c 14a0fff8 bnez $a1, 0x13cb60
0013cb80 254a0001 addiu $t2, $t2, 1
0013cb84 00000000 nop 
0013cb88 3c01004f lui $at, 0x4f
0013cb8c 8423d5e0 lh $v1, -0x2a20($at)
0013cb90 00152c3c dsll32 $a1, $s5, 0x10
0013cb94 0014343c dsll32 $a2, $s4, 0x10
0013cb98 3c04004a lui $a0, 0x4a
0013cb9c 0100382d move $a3, $t0
0013cba0 00052c3f dsra32 $a1, $a1, 0x10
0013cba4 0006343f dsra32 $a2, $a2, 0x10
0013cba8 24847710 addiu $a0, $a0, 0x7710
0013cbac 0000482d move $t1, $zero
0013cbb0 0240402d move $t0, $s2
0013cbb4 3c01004f lui $at, 0x4f
0013cbb8 8422d5f4 lh $v0, -0x2a0c($at)
0013cbbc 01431818 mult $v1, $t2, $v1
0013cbc0 00a31823 subu $v1, $a1, $v1
0013cbc4 0c04f414 jal 0x13d050
0013cbc8 00622823 subu $a1, $v1, $v0
0013cbcc 0200202d move $a0, $s0
0013cbd0 02a0282d move $a1, $s5
0013cbd4 0280302d move $a2, $s4
0013cbd8 0260382d move $a3, $s3
0013cbdc 0240482d move $t1, $s2
0013cbe0 0220502d move $t2, $s1
0013cbe4 0c04f200 jal 0x13c800
0013cbe8 0040402d move $t0, $v0
0013cbec 10000004 b 0x13cc00
0013cbf0 00000000 nop 
0013cbf4 00000000 nop 
0013cbf8 0c04f200 jal 0x13c800
0013cbfc 00000000 nop 
0013cc00 dfbf0060 ld $ra, 0x60($sp)
0013cc04 7bb50050 lq $s5, 80($sp)
0013cc08 7bb40040 lq $s4, 64($sp)
0013cc0c 7bb30030 lq $s3, 48($sp)
0013cc10 7bb20020 lq $s2, 32($sp)
0013cc14 7bb10010 lq $s1, 16($sp)
0013cc18 7bb00000 lq $s0, 0($sp)
0013cc1c 03e00008 jr $ra
0013cc20 27bd0070 addiu $sp, $sp, 0x70
0013cc24 00000000 nop 
0013cc28 00000000 nop 
0013cc2c 00000000 nop 

; symbol_list 0013cc30..0013ce40
0013cc30 27bdffc0 addiu $sp, $sp, -0x40
0013cc34 ffbf0030 sd $ra, 0x30($sp)
0013cc38 7fb20020 sq $s2, 32($sp)
0013cc3c 7fb10010 sq $s1, 16($sp)
0013cc40 11000007 beqz $t0, 0x13cc60
0013cc44 7fb00000 sq $s0, 0($sp)
0013cc48 3c01004f lui $at, 0x4f
0013cc4c 8c32d610 lw $s2, -0x29f0($at)
0013cc50 3c01004f lui $at, 0x4f
0013cc54 8431d5b0 lh $s1, -0x2a50($at)
0013cc58 3c01004f lui $at, 0x4f
0013cc5c 8430d5b2 lh $s0, -0x2a4e($at)
0013cc60 2402ffff addiu $v0, $zero, -1
0013cc64 11220002 beq $t1, $v0, 0x13cc70
0013cc68 3c01004f lui $at, 0x4f
0013cc6c ac29d5e4 sw $t1, -0x2a1c($at)
0013cc70 3c01004f lui $at, 0x4f
0013cc74 a425d61a sh $a1, -0x29e6($at)
0013cc78 3c01004f lui $at, 0x4f
0013cc7c 848d0000 lh $t5, ($a0)
0013cc80 9423d5b2 lhu $v1, -0x2a4e($at)
0013cc84 3c01004f lui $at, 0x4f
0013cc88 00031940 sll $v1, $v1, 5
0013cc8c 8c22d610 lw $v0, -0x29f0($at)
0013cc90 11a00049 beqz $t5, 0x13cdb8
0013cc94 00434821 addu $t1, $v0, $v1
0013cc98 3c0230c3 lui $v0, 0x30c3
0013cc9c 24030015 addiu $v1, $zero, 0x15
0013cca0 34420c31 ori $v0, $v0, 0xc31
0013cca4 240c0024 addiu $t4, $zero, 0x24
0013cca8 3c010045 lui $at, 0x45
0013ccac 8c2e2888 lw $t6, 0x2888($at)
0013ccb0 85cb0000 lh $t3, ($t6)
0013ccb4 11ab000a beq $t5, $t3, 0x13cce0
0013ccb8 0000782d move $t7, $zero
0013ccbc 00000000 nop 
0013ccc0 25ce0002 addiu $t6, $t6, 2
0013ccc4 85cb0000 lh $t3, ($t6)
0013ccc8 25ef0001 addiu $t7, $t7, 1
0013cccc 00000000 nop 
0013ccd0 00000000 nop 
0013ccd4 15abfffa bne $t5, $t3, 0x13ccc0
0013ccd8 00000000 nop 
0013ccdc 00000000 nop 
0013cce0 a5250004 sh $a1, 4($t1)
0013cce4 01e3001a div $zero, $t7, $v1
0013cce8 00a72821 addu $a1, $a1, $a3
0013ccec 00052c3c dsll32 $a1, $a1, 0x10
0013ccf0 a5260006 sh $a2, 6($t1)
0013ccf4 3c01004f lui $at, 0x4f
0013ccf8 000f6fc2 srl $t5, $t7, 0x1f
0013ccfc 8c2bd5e4 lw $t3, -0x2a1c($at)
0013cd00 24840002 addiu $a0, $a0, 2
0013cd04 00052c3f dsra32 $a1, $a1, 0x10
0013cd08 ad2b0008 sw $t3, 8($t1)
0013cd0c 3c01004f lui $at, 0x4f
0013cd10 00007010 mfhi $t6
0013cd14 000e5840 sll $t3, $t6, 1
0013cd18 016e5821 addu $t3, $t3, $t6
0013cd1c 000b58c0 sll $t3, $t3, 3
0013cd20 004f0018 mult $v0, $t7
0013cd24 a52b0000 sh $t3, ($t1)
0013cd28 00000000 nop 
0013cd2c 00005810 mfhi $t3
0013cd30 000b5883 sra $t3, $t3, 2
0013cd34 016d6821 addu $t5, $t3, $t5
0013cd38 000d5840 sll $t3, $t5, 1
0013cd3c 016d5821 addu $t3, $t3, $t5
0013cd40 000b58c0 sll $t3, $t3, 3
0013cd44 a52b0002 sh $t3, 2($t1)
0013cd48 a127000c sb $a3, 0xc($t1)
0013cd4c 842bd5de lh $t3, -0x2a22($at)
0013cd50 a12b000d sb $t3, 0xd($t1)
0013cd54 3c01004f lui $at, 0x4f
0013cd58 842bd5e2 lh $t3, -0x2a1e($at)
0013cd5c a12b000e sb $t3, 0xe($t1)
0013cd60 3c01004f lui $at, 0x4f
0013cd64 a12c000f sb $t4, 0xf($t1)
0013cd68 902bd5fa lbu $t3, -0x2a06($at)
0013cd6c a12b0010 sb $t3, 0x10($t1)
0013cd70 3c01004f lui $at, 0x4f
0013cd74 8c2bd5d4 lw $t3, -0x2a2c($at)
0013cd78 ad2b0014 sw $t3, 0x14($t1)
0013cd7c 3c01004f lui $at, 0x4f
0013cd80 8c2bd5d8 lw $t3, -0x2a28($at)
0013cd84 ad2b0018 sw $t3, 0x18($t1)
0013cd88 3c01004f lui $at, 0x4f
0013cd8c 802bd600 lb $t3, -0x2a00($at)
0013cd90 a12b001c sb $t3, 0x1c($t1)
0013cd94 3c01004f lui $at, 0x4f
0013cd98 942bd5b2 lhu $t3, -0x2a4e($at)
0013cd9c 256b0001 addiu $t3, $t3, 1
0013cda0 3c01004f lui $at, 0x4f
0013cda4 a42bd5b2 sh $t3, -0x2a4e($at)
0013cda8 848d0000 lh $t5, ($a0)
0013cdac 15a0ffbe bnez $t5, 0x13cca8
0013cdb0 25290020 addiu $t1, $t1, 0x20
0013cdb4 00000000 nop 
0013cdb8 11000017 beqz $t0, 0x13ce18
0013cdbc 3c01004f lui $at, 0x4f
0013cdc0 0010343c dsll32 $a2, $s0, 0x10
0013cdc4 a420d5b0 sh $zero, -0x2a50($at)
0013cdc8 0006343f dsra32 $a2, $a2, 0x10
0013cdcc 3c01004f lui $at, 0x4f
0013cdd0 00061940 sll $v1, $a2, 5
0013cdd4 9422d5b2 lhu $v0, -0x2a4e($at)
0013cdd8 02431821 addu $v1, $s2, $v1
0013cddc 0100202d move $a0, $t0
0013cde0 0140282d move $a1, $t2
0013cde4 3c01004f lui $at, 0x4f
0013cde8 00461023 subu $v0, $v0, $a2
0013cdec ac23d610 sw $v1, -0x29f0($at)
0013cdf0 3c01004f lui $at, 0x4f
0013cdf4 0c04edd0 jal 0x13b740
0013cdf8 a422d5b2 sh $v0, -0x2a4e($at)
0013cdfc 3c01004f lui $at, 0x4f
0013ce00 0040402d move $t0, $v0
0013ce04 ac32d610 sw $s2, -0x29f0($at)
0013ce08 3c01004f lui $at, 0x4f
0013ce0c a431d5b0 sh $s1, -0x2a50($at)
0013ce10 3c01004f lui $at, 0x4f
0013ce14 a430d5b2 sh $s0, -0x2a4e($at)
0013ce18 dfbf0030 ld $ra, 0x30($sp)
0013ce1c 7bb20020 lq $s2, 32($sp)
0013ce20 0100102d move $v0, $t0
0013ce24 7bb10010 lq $s1, 16($sp)
0013ce28 7bb00000 lq $s0, 0($sp)
0013ce2c 03e00008 jr $ra
0013ce30 27bd0040 addiu $sp, $sp, 0x40
0013ce34 00000000 nop 
0013ce38 00000000 nop 
0013ce3c 00000000 nop 

; initialize_record_group 0013cec0..0013d050
0013cec0 00041940 sll $v1, $a0, 5
0013cec4 3c01004f lui $at, 0x4f
0013cec8 00642021 addu $a0, $v1, $a0
0013cecc 0000402d move $t0, $zero
0013ced0 8c23d608 lw $v1, -0x29f8($at)
0013ced4 00042180 sll $a0, $a0, 6
0013ced8 00643821 addu $a3, $v1, $a0
0013cedc 2406ff38 addiu $a2, $zero, -0xc8
0013cee0 24050001 addiu $a1, $zero, 1
0013cee4 24040080 addiu $a0, $zero, 0x80
0013cee8 a4e00000 sh $zero, ($a3)
0013ceec a4e00002 sh $zero, 2($a3)
0013cef0 25080008 addiu $t0, $t0, 8
0013cef4 a4e00004 sh $zero, 4($a3)
0013cef8 2903003a slti $v1, $t0, 0x3a
0013cefc a4e60006 sh $a2, 6($a3)
0013cf00 ace00008 sw $zero, 8($a3)
0013cf04 a4e5000c sh $a1, 0xc($a3)
0013cf08 a4e5000e sh $a1, 0xe($a3)
0013cf0c a0e40010 sb $a0, 0x10($a3)
0013cf10 a4e00020 sh $zero, 0x20($a3)
0013cf14 a4e00022 sh $zero, 0x22($a3)
0013cf18 a4e00024 sh $zero, 0x24($a3)
0013cf1c a4e60026 sh $a2, 0x26($a3)
0013cf20 ace00028 sw $zero, 0x28($a3)
0013cf24 a4e5002c sh $a1, 0x2c($a3)
0013cf28 a4e5002e sh $a1, 0x2e($a3)
0013cf2c a0e40030 sb $a0, 0x30($a3)
0013cf30 24e70040 addiu $a3, $a3, 0x40
0013cf34 a4e00000 sh $zero, ($a3)
0013cf38 a4e00002 sh $zero, 2($a3)
0013cf3c a4e00004 sh $zero, 4($a3)
0013cf40 a4e60006 sh $a2, 6($a3)
0013cf44 ace00008 sw $zero, 8($a3)
0013cf48 a4e5000c sh $a1, 0xc($a3)
0013cf4c a4e5000e sh $a1, 0xe($a3)
0013cf50 a0e40010 sb $a0, 0x10($a3)
0013cf54 a4e00020 sh $zero, 0x20($a3)
0013cf58 a4e00022 sh $zero, 0x22($a3)
0013cf5c a4e00024 sh $zero, 0x24($a3)
0013cf60 a4e60026 sh $a2, 0x26($a3)
0013cf64 ace00028 sw $zero, 0x28($a3)
0013cf68 a4e5002c sh $a1, 0x2c($a3)
0013cf6c a4e5002e sh $a1, 0x2e($a3)
0013cf70 a0e40030 sb $a0, 0x30($a3)
0013cf74 24e70040 addiu $a3, $a3, 0x40
0013cf78 a4e00000 sh $zero, ($a3)
0013cf7c a4e00002 sh $zero, 2($a3)
0013cf80 a4e00004 sh $zero, 4($a3)
0013cf84 a4e60006 sh $a2, 6($a3)
0013cf88 ace00008 sw $zero, 8($a3)
0013cf8c a4e5000c sh $a1, 0xc($a3)
0013cf90 a4e5000e sh $a1, 0xe($a3)
0013cf94 a0e40010 sb $a0, 0x10($a3)
0013cf98 a4e00020 sh $zero, 0x20($a3)
0013cf9c a4e00022 sh $zero, 0x22($a3)
0013cfa0 a4e00024 sh $zero, 0x24($a3)
0013cfa4 a4e60026 sh $a2, 0x26($a3)
0013cfa8 ace00028 sw $zero, 0x28($a3)
0013cfac a4e5002c sh $a1, 0x2c($a3)
0013cfb0 a4e5002e sh $a1, 0x2e($a3)
0013cfb4 a0e40030 sb $a0, 0x30($a3)
0013cfb8 24e70040 addiu $a3, $a3, 0x40
0013cfbc a4e00000 sh $zero, ($a3)
0013cfc0 a4e00002 sh $zero, 2($a3)
0013cfc4 a4e00004 sh $zero, 4($a3)
0013cfc8 a4e60006 sh $a2, 6($a3)
0013cfcc ace00008 sw $zero, 8($a3)
0013cfd0 a4e5000c sh $a1, 0xc($a3)
0013cfd4 a4e5000e sh $a1, 0xe($a3)
0013cfd8 a0e40010 sb $a0, 0x10($a3)
0013cfdc a4e00020 sh $zero, 0x20($a3)
0013cfe0 a4e00022 sh $zero, 0x22($a3)
0013cfe4 a4e00024 sh $zero, 0x24($a3)
0013cfe8 a4e60026 sh $a2, 0x26($a3)
0013cfec ace00028 sw $zero, 0x28($a3)
0013cff0 a4e5002c sh $a1, 0x2c($a3)
0013cff4 a4e5002e sh $a1, 0x2e($a3)
0013cff8 a0e40030 sb $a0, 0x30($a3)
0013cffc 1460ffba bnez $v1, 0x13cee8
0013d000 24e70040 addiu $a3, $a3, 0x40
0013d004 a4e00000 sh $zero, ($a3)
0013d008 a4e00002 sh $zero, 2($a3)
0013d00c a4e00004 sh $zero, 4($a3)
0013d010 a4e60006 sh $a2, 6($a3)
0013d014 ace00008 sw $zero, 8($a3)
0013d018 a4e5000c sh $a1, 0xc($a3)
0013d01c a4e5000e sh $a1, 0xe($a3)
0013d020 a0e40010 sb $a0, 0x10($a3)
0013d024 a4e00020 sh $zero, 0x20($a3)
0013d028 a4e00022 sh $zero, 0x22($a3)
0013d02c a4e00024 sh $zero, 0x24($a3)
0013d030 a4e60026 sh $a2, 0x26($a3)
0013d034 ace00028 sw $zero, 0x28($a3)
0013d038 a4e5002c sh $a1, 0x2c($a3)
0013d03c a4e5002e sh $a1, 0x2e($a3)
0013d040 03e00008 jr $ra
0013d044 a0e40030 sb $a0, 0x30($a3)
0013d048 00000000 nop 
0013d04c 00000000 nop 

; text_at_position 0013d050..0013d070
0013d050 3c01004f lui $at, 0x4f
0013d054 a425d5c0 sh $a1, -0x2a40($at)
0013d058 3c01004f lui $at, 0x4f
0013d05c 00e0282d move $a1, $a3
0013d060 a426d5c2 sh $a2, -0x2a3e($at)
0013d064 0120382d move $a3, $t1
0013d068 0804eb4c j 0x13ad30
0013d06c 0100302d move $a2, $t0
