; cached_symbol_setup 003aa000..003aa1a0
003aa000 27bdfdc0 addiu $sp, $sp, -0x240
003aa004 3c010047 lui $at, 0x47
003aa008 ffbf0030 sd $ra, 0x30($sp)
003aa00c 7fb20020 sq $s2, 32($sp)
003aa010 7fb10010 sq $s1, 16($sp)
003aa014 7fb00000 sq $s0, 0($sp)
003aa018 9032eb7a lbu $s2, -0x1486($at)
003aa01c 3c010047 lui $at, 0x47
003aa020 8031eb80 lb $s1, -0x1480($at)
003aa024 0c04e694 jal 0x139a50
003aa028 0000202d move $a0, $zero
003aa02c 0c04e6bc jal 0x139af0
003aa030 0000202d move $a0, $zero
003aa034 3c040044 lui $a0, 0x44
003aa038 0000282d move $a1, $zero
003aa03c 24844e30 addiu $a0, $a0, 0x4e30
003aa040 0000302d move $a2, $zero
003aa044 0000382d move $a3, $zero
003aa048 27a80040 addiu $t0, $sp, 0x40
003aa04c 0000482d move $t1, $zero
003aa050 0c04f064 jal 0x13c190
003aa054 0000502d move $t2, $zero
003aa058 27b00040 addiu $s0, $sp, 0x40
003aa05c 3c04006d lui $a0, 0x6d
003aa060 0000302d move $a2, $zero
003aa064 0200282d move $a1, $s0
003aa068 24846960 addiu $a0, $a0, 0x6960
003aa06c 00000000 nop 
003aa070 78a30000 lq $v1, 0($a1)
003aa074 24c20006 addiu $v0, $a2, 6
003aa078 0002343c dsll32 $a2, $v0, 0x10
003aa07c 0006343f dsra32 $a2, $a2, 0x10
003aa080 28c20007 slti $v0, $a2, 7
003aa084 7c830000 sq $v1, 0($a0)
003aa088 78a30010 lq $v1, 16($a1)
003aa08c 7c830010 sq $v1, 16($a0)
003aa090 78a30020 lq $v1, 32($a1)
003aa094 7c830020 sq $v1, 32($a0)
003aa098 78a30030 lq $v1, 48($a1)
003aa09c 7c830030 sq $v1, 48($a0)
003aa0a0 78a30040 lq $v1, 64($a1)
003aa0a4 7c830040 sq $v1, 64($a0)
003aa0a8 78a30050 lq $v1, 80($a1)
003aa0ac 7c830050 sq $v1, 80($a0)
003aa0b0 24a50060 addiu $a1, $a1, 0x60
003aa0b4 1440ffee bnez $v0, 0x3aa070
003aa0b8 24840060 addiu $a0, $a0, 0x60
003aa0bc 3c02006d lui $v0, 0x6d
003aa0c0 00061900 sll $v1, $a2, 4
003aa0c4 24426960 addiu $v0, $v0, 0x6960
003aa0c8 3c040044 lui $a0, 0x44
003aa0cc 00431021 addu $v0, $v0, $v1
003aa0d0 24844e10 addiu $a0, $a0, 0x4e10
003aa0d4 007d1821 addu $v1, $v1, $sp
003aa0d8 0000282d move $a1, $zero
003aa0dc 78630040 lq $v1, 64($v1)
003aa0e0 0000302d move $a2, $zero
003aa0e4 0000382d move $a3, $zero
003aa0e8 27a80040 addiu $t0, $sp, 0x40
003aa0ec 0000482d move $t1, $zero
003aa0f0 0000502d move $t2, $zero
003aa0f4 0c04f064 jal 0x13c190
003aa0f8 7c430000 sq $v1, 0($v0)
003aa0fc 3c05006d lui $a1, 0x6d
003aa100 0000302d move $a2, $zero
003aa104 24a56890 addiu $a1, $a1, 0x6890
003aa108 7a040000 lq $a0, 0($s0)
003aa10c 24c30006 addiu $v1, $a2, 6
003aa110 0003343c dsll32 $a2, $v1, 0x10
003aa114 0006343f dsra32 $a2, $a2, 0x10
003aa118 28c30007 slti $v1, $a2, 7
003aa11c 7ca40000 sq $a0, 0($a1)
003aa120 7a040010 lq $a0, 16($s0)
003aa124 7ca40010 sq $a0, 16($a1)
003aa128 7a040020 lq $a0, 32($s0)
003aa12c 7ca40020 sq $a0, 32($a1)
003aa130 7a040030 lq $a0, 48($s0)
003aa134 7ca40030 sq $a0, 48($a1)
003aa138 7a040040 lq $a0, 64($s0)
003aa13c 7ca40040 sq $a0, 64($a1)
003aa140 7a040050 lq $a0, 80($s0)
003aa144 7ca40050 sq $a0, 80($a1)
003aa148 26100060 addiu $s0, $s0, 0x60
003aa14c 1460ffee bnez $v1, 0x3aa108
003aa150 24a50060 addiu $a1, $a1, 0x60
003aa154 3c03006d lui $v1, 0x6d
003aa158 00062100 sll $a0, $a2, 4
003aa15c 24636890 addiu $v1, $v1, 0x6890
003aa160 3c010047 lui $at, 0x47
003aa164 00641821 addu $v1, $v1, $a0
003aa168 009d2021 addu $a0, $a0, $sp
003aa16c 78840040 lq $a0, 64($a0)
003aa170 7c640000 sq $a0, 0($v1)
003aa174 a032eb7a sb $s2, -0x1486($at)
003aa178 3c010047 lui $at, 0x47
003aa17c a031eb80 sb $s1, -0x1480($at)
003aa180 dfbf0030 ld $ra, 0x30($sp)
003aa184 7bb20020 lq $s2, 32($sp)
003aa188 7bb10010 lq $s1, 16($sp)
003aa18c 7bb00000 lq $s0, 0($sp)
003aa190 03e00008 jr $ra
003aa194 27bd0240 addiu $sp, $sp, 0x240
003aa198 00000000 nop 
003aa19c 00000000 nop 
; repeat_renderer 003aa1a0..003aa700
003aa1a0 27bdffa0 addiu $sp, $sp, -0x60
003aa1a4 24020040 addiu $v0, $zero, 0x40
003aa1a8 ffbf0050 sd $ra, 0x50($sp)
003aa1ac 7fb40040 sq $s4, 64($sp)
003aa1b0 7fb30030 sq $s3, 48($sp)
003aa1b4 0080a02d move $s4, $a0
003aa1b8 7fb20020 sq $s2, 32($sp)
003aa1bc 00a0982d move $s3, $a1
003aa1c0 7fb10010 sq $s1, 16($sp)
003aa1c4 00c0902d move $s2, $a2
003aa1c8 7fb00000 sq $s0, 0($sp)
003aa1cc 00e0882d move $s1, $a3
003aa1d0 80830000 lb $v1, ($a0)
003aa1d4 1462013e bne $v1, $v0, 0x3aa6d0
003aa1d8 0100802d move $s0, $t0
003aa1dc 3c010043 lui $at, 0x43
003aa1e0 8c22fbb8 lw $v0, -0x448($at)
003aa1e4 10400006 beqz $v0, 0x3aa200
003aa1e8 00000000 nop 
003aa1ec 0c0ea800 jal 0x3aa000
003aa1f0 00000000 nop 
003aa1f4 3c010043 lui $at, 0x43
003aa1f8 ac20fbb8 sw $zero, -0x448($at)
003aa1fc 00000000 nop 
003aa200 0c066a4a jal 0x19a928
003aa204 26840001 addiu $a0, $s4, 1
003aa208 34018000 ori $at, $zero, 0x8000
003aa20c 3c090047 lui $t1, 0x47
003aa210 0041082a slt $at, $v0, $at
003aa214 14200002 bnez $at, 0x3aa220
003aa218 2529eb30 addiu $t1, $t1, -0x14d0
003aa21c 24027fff addiu $v0, $zero, 0x7fff
003aa220 3c01006d lui $at, 0x6d
003aa224 78266960 lq $a2, 26976($at)
003aa228 264c0800 addiu $t4, $s2, 0x800
003aa22c 852b0042 lh $t3, 0x42($t1)
003aa230 26630800 addiu $v1, $s3, 0x800
003aa234 0003443c dsll32 $t0, $v1, 0x10
003aa238 3c05006d lui $a1, 0x6d
003aa23c 24437fff addiu $v1, $v0, 0x7fff
003aa240 0008443f dsra32 $t0, $t0, 0x10
003aa244 246a0001 addiu $t2, $v1, 1
003aa248 000c3d00 sll $a3, $t4, 0x14
003aa24c 00081900 sll $v1, $t0, 4
003aa250 24a56a00 addiu $a1, $a1, 0x6a00
003aa254 3c01006d lui $at, 0x6d
003aa258 00e31825 or $v1, $a3, $v1
003aa25c 018b5821 addu $t3, $t4, $t3
003aa260 7e260000 sq $a2, 0($s1)
003aa264 000b3500 sll $a2, $t3, 0x14
003aa268 0000202d move $a0, $zero
003aa26c 782b6970 lq $t3, 26992($at)
003aa270 7e2b0010 sq $t3, 16($s1)
003aa274 3c01006d lui $at, 0x6d
003aa278 782b6980 lq $t3, 27008($at)
003aa27c 7e2b0020 sq $t3, 32($s1)
003aa280 3c01006d lui $at, 0x6d
003aa284 782b6990 lq $t3, 27024($at)
003aa288 7e2b0030 sq $t3, 48($s1)
003aa28c 3c01006d lui $at, 0x6d
003aa290 782b69a0 lq $t3, 27040($at)
003aa294 7e2b0040 sq $t3, 64($s1)
003aa298 3c01006d lui $at, 0x6d
003aa29c 782b69b0 lq $t3, 27056($at)
003aa2a0 7e2b0050 sq $t3, 80($s1)
003aa2a4 3c01006d lui $at, 0x6d
003aa2a8 782b69c0 lq $t3, 27072($at)
003aa2ac 7e2b0060 sq $t3, 96($s1)
003aa2b0 3c01006d lui $at, 0x6d
003aa2b4 782b69d0 lq $t3, 27088($at)
003aa2b8 7e2b0070 sq $t3, 112($s1)
003aa2bc 3c01006d lui $at, 0x6d
003aa2c0 a42a69e0 sh $t2, 0x69e0($at)
003aa2c4 852a001c lh $t2, 0x1c($t1)
003aa2c8 3c01006d lui $at, 0x6d
003aa2cc a02a69ff sb $t2, 0x69ff($at)
003aa2d0 8d2a0024 lw $t2, 0x24($t1)
003aa2d4 3c01006d lui $at, 0x6d
003aa2d8 acaa0000 sw $t2, ($a1)
003aa2dc aca30010 sw $v1, 0x10($a1)
003aa2e0 acb00014 sw $s0, 0x14($a1)
003aa2e4 85230040 lh $v1, 0x40($t1)
003aa2e8 01031821 addu $v1, $t0, $v1
003aa2ec 00031900 sll $v1, $v1, 4
003aa2f0 00c31825 or $v1, $a2, $v1
003aa2f4 aca30020 sw $v1, 0x20($a1)
003aa2f8 acb00024 sw $s0, 0x24($a1)
003aa2fc 782369e0 lq $v1, 27104($at)
003aa300 7e230080 sq $v1, 128($s1)
003aa304 0002082a slt $at, $zero, $v0
003aa308 102000ef beqz $at, 0x3aa6c8
003aa30c 26310090 addiu $s1, $s1, 0x90
003aa310 28410009 slti $at, $v0, 9
003aa314 142000c8 bnez $at, 0x3aa638
003aa318 2443fff8 addiu $v1, $v0, -8
003aa31c 00000000 nop 
003aa320 3c01006d lui $at, 0x6d
003aa324 782b69f0 lq $t3, 27120($at)
003aa328 24840008 addiu $a0, $a0, 8
003aa32c 0004243c dsll32 $a0, $a0, 0x10
003aa330 0004243f dsra32 $a0, $a0, 0x10
003aa334 0083502a slt $t2, $a0, $v1
003aa338 7e2b0000 sq $t3, 0($s1)
003aa33c 3c01006d lui $at, 0x6d
003aa340 782b6a00 lq $t3, 27136($at)
003aa344 7e2b0010 sq $t3, 16($s1)
003aa348 3c01006d lui $at, 0x6d
003aa34c 782b6a10 lq $t3, 27152($at)
003aa350 7e2b0020 sq $t3, 32($s1)
003aa354 3c01006d lui $at, 0x6d
003aa358 782b6a20 lq $t3, 27168($at)
003aa35c 7e2b0030 sq $t3, 48($s1)
003aa360 3c01006d lui $at, 0x6d
003aa364 852b0044 lh $t3, 0x44($t1)
003aa368 010b4021 addu $t0, $t0, $t3
003aa36c 0008443c dsll32 $t0, $t0, 0x10
003aa370 0008443f dsra32 $t0, $t0, 0x10
003aa374 00085900 sll $t3, $t0, 4
003aa378 00eb5825 or $t3, $a3, $t3
003aa37c acab0010 sw $t3, 0x10($a1)
003aa380 852b0040 lh $t3, 0x40($t1)
003aa384 010b5821 addu $t3, $t0, $t3
003aa388 000b5900 sll $t3, $t3, 4
003aa38c 00cb5825 or $t3, $a2, $t3
003aa390 acab0020 sw $t3, 0x20($a1)
003aa394 782b69f0 lq $t3, 27120($at)
003aa398 7e2b0040 sq $t3, 64($s1)
003aa39c 3c01006d lui $at, 0x6d
003aa3a0 782b6a00 lq $t3, 27136($at)
003aa3a4 7e2b0050 sq $t3, 80($s1)
003aa3a8 3c01006d lui $at, 0x6d
003aa3ac 782b6a10 lq $t3, 27152($at)
003aa3b0 7e2b0060 sq $t3, 96($s1)
003aa3b4 3c01006d lui $at, 0x6d
003aa3b8 782b6a20 lq $t3, 27168($at)
003aa3bc 7e2b0070 sq $t3, 112($s1)
003aa3c0 3c01006d lui $at, 0x6d
003aa3c4 852b0044 lh $t3, 0x44($t1)
003aa3c8 010b4021 addu $t0, $t0, $t3
003aa3cc 0008443c dsll32 $t0, $t0, 0x10
003aa3d0 0008443f dsra32 $t0, $t0, 0x10
003aa3d4 00085900 sll $t3, $t0, 4
003aa3d8 00eb5825 or $t3, $a3, $t3
003aa3dc acab0010 sw $t3, 0x10($a1)
003aa3e0 852b0040 lh $t3, 0x40($t1)
003aa3e4 010b5821 addu $t3, $t0, $t3
003aa3e8 000b5900 sll $t3, $t3, 4
003aa3ec 00cb5825 or $t3, $a2, $t3
003aa3f0 acab0020 sw $t3, 0x20($a1)
003aa3f4 782b69f0 lq $t3, 27120($at)
003aa3f8 7e2b0080 sq $t3, 128($s1)
003aa3fc 3c01006d lui $at, 0x6d
003aa400 782b6a00 lq $t3, 27136($at)
003aa404 7e2b0090 sq $t3, 144($s1)
003aa408 3c01006d lui $at, 0x6d
003aa40c 782b6a10 lq $t3, 27152($at)
003aa410 7e2b00a0 sq $t3, 160($s1)
003aa414 3c01006d lui $at, 0x6d
003aa418 782b6a20 lq $t3, 27168($at)
003aa41c 7e2b00b0 sq $t3, 176($s1)
003aa420 3c01006d lui $at, 0x6d
003aa424 852b0044 lh $t3, 0x44($t1)
003aa428 010b4021 addu $t0, $t0, $t3
003aa42c 0008443c dsll32 $t0, $t0, 0x10
003aa430 0008443f dsra32 $t0, $t0, 0x10
003aa434 00085900 sll $t3, $t0, 4
003aa438 00eb5825 or $t3, $a3, $t3
003aa43c acab0010 sw $t3, 0x10($a1)
003aa440 852b0040 lh $t3, 0x40($t1)
003aa444 010b5821 addu $t3, $t0, $t3
003aa448 000b5900 sll $t3, $t3, 4
003aa44c 00cb5825 or $t3, $a2, $t3
003aa450 acab0020 sw $t3, 0x20($a1)
003aa454 782b69f0 lq $t3, 27120($at)
003aa458 7e2b00c0 sq $t3, 192($s1)
003aa45c 3c01006d lui $at, 0x6d
003aa460 782b6a00 lq $t3, 27136($at)
003aa464 7e2b00d0 sq $t3, 208($s1)
003aa468 3c01006d lui $at, 0x6d
003aa46c 782b6a10 lq $t3, 27152($at)
003aa470 7e2b00e0 sq $t3, 224($s1)
003aa474 3c01006d lui $at, 0x6d
003aa478 782b6a20 lq $t3, 27168($at)
003aa47c 7e2b00f0 sq $t3, 240($s1)
003aa480 3c01006d lui $at, 0x6d
003aa484 852b0044 lh $t3, 0x44($t1)
003aa488 010b4021 addu $t0, $t0, $t3
003aa48c 0008443c dsll32 $t0, $t0, 0x10
003aa490 0008443f dsra32 $t0, $t0, 0x10
003aa494 00085900 sll $t3, $t0, 4
003aa498 00eb5825 or $t3, $a3, $t3
003aa49c acab0010 sw $t3, 0x10($a1)
003aa4a0 852b0040 lh $t3, 0x40($t1)
003aa4a4 010b5821 addu $t3, $t0, $t3
003aa4a8 000b5900 sll $t3, $t3, 4
003aa4ac 00cb5825 or $t3, $a2, $t3
003aa4b0 acab0020 sw $t3, 0x20($a1)
003aa4b4 782b69f0 lq $t3, 27120($at)
003aa4b8 7e2b0100 sq $t3, 256($s1)
003aa4bc 3c01006d lui $at, 0x6d
003aa4c0 782b6a00 lq $t3, 27136($at)
003aa4c4 7e2b0110 sq $t3, 272($s1)
003aa4c8 3c01006d lui $at, 0x6d
003aa4cc 782b6a10 lq $t3, 27152($at)
003aa4d0 7e2b0120 sq $t3, 288($s1)
003aa4d4 3c01006d lui $at, 0x6d
003aa4d8 782b6a20 lq $t3, 27168($at)
003aa4dc 7e2b0130 sq $t3, 304($s1)
003aa4e0 3c01006d lui $at, 0x6d
003aa4e4 852b0044 lh $t3, 0x44($t1)
003aa4e8 010b4021 addu $t0, $t0, $t3
003aa4ec 0008443c dsll32 $t0, $t0, 0x10
003aa4f0 0008443f dsra32 $t0, $t0, 0x10
003aa4f4 00085900 sll $t3, $t0, 4
003aa4f8 00eb5825 or $t3, $a3, $t3
003aa4fc acab0010 sw $t3, 0x10($a1)
003aa500 852b0040 lh $t3, 0x40($t1)
003aa504 010b5821 addu $t3, $t0, $t3
003aa508 000b5900 sll $t3, $t3, 4
003aa50c 00cb5825 or $t3, $a2, $t3
003aa510 acab0020 sw $t3, 0x20($a1)
003aa514 782b69f0 lq $t3, 27120($at)
003aa518 7e2b0140 sq $t3, 320($s1)
003aa51c 3c01006d lui $at, 0x6d
003aa520 782b6a00 lq $t3, 27136($at)
003aa524 7e2b0150 sq $t3, 336($s1)
003aa528 3c01006d lui $at, 0x6d
003aa52c 782b6a10 lq $t3, 27152($at)
003aa530 7e2b0160 sq $t3, 352($s1)
003aa534 3c01006d lui $at, 0x6d
003aa538 782b6a20 lq $t3, 27168($at)
003aa53c 7e2b0170 sq $t3, 368($s1)
003aa540 3c01006d lui $at, 0x6d
003aa544 852b0044 lh $t3, 0x44($t1)
003aa548 010b4021 addu $t0, $t0, $t3
003aa54c 0008443c dsll32 $t0, $t0, 0x10
003aa550 0008443f dsra32 $t0, $t0, 0x10
003aa554 00085900 sll $t3, $t0, 4
003aa558 00eb5825 or $t3, $a3, $t3
003aa55c acab0010 sw $t3, 0x10($a1)
003aa560 852b0040 lh $t3, 0x40($t1)
003aa564 010b5821 addu $t3, $t0, $t3
003aa568 000b5900 sll $t3, $t3, 4
003aa56c 00cb5825 or $t3, $a2, $t3
003aa570 acab0020 sw $t3, 0x20($a1)
003aa574 782b69f0 lq $t3, 27120($at)
003aa578 7e2b0180 sq $t3, 384($s1)
003aa57c 3c01006d lui $at, 0x6d
003aa580 782b6a00 lq $t3, 27136($at)
003aa584 7e2b0190 sq $t3, 400($s1)
003aa588 3c01006d lui $at, 0x6d
003aa58c 782b6a10 lq $t3, 27152($at)
003aa590 7e2b01a0 sq $t3, 416($s1)
003aa594 3c01006d lui $at, 0x6d
003aa598 782b6a20 lq $t3, 27168($at)
003aa59c 7e2b01b0 sq $t3, 432($s1)
003aa5a0 3c01006d lui $at, 0x6d
003aa5a4 852b0044 lh $t3, 0x44($t1)
003aa5a8 010b4021 addu $t0, $t0, $t3
003aa5ac 0008443c dsll32 $t0, $t0, 0x10
003aa5b0 0008443f dsra32 $t0, $t0, 0x10
003aa5b4 00085900 sll $t3, $t0, 4
003aa5b8 00eb5825 or $t3, $a3, $t3
003aa5bc acab0010 sw $t3, 0x10($a1)
003aa5c0 852b0040 lh $t3, 0x40($t1)
003aa5c4 010b5821 addu $t3, $t0, $t3
003aa5c8 000b5900 sll $t3, $t3, 4
003aa5cc 00cb5825 or $t3, $a2, $t3
003aa5d0 acab0020 sw $t3, 0x20($a1)
003aa5d4 782b69f0 lq $t3, 27120($at)
003aa5d8 7e2b01c0 sq $t3, 448($s1)
003aa5dc 3c01006d lui $at, 0x6d
003aa5e0 782b6a00 lq $t3, 27136($at)
003aa5e4 7e2b01d0 sq $t3, 464($s1)
003aa5e8 3c01006d lui $at, 0x6d
003aa5ec 782b6a10 lq $t3, 27152($at)
003aa5f0 7e2b01e0 sq $t3, 480($s1)
003aa5f4 3c01006d lui $at, 0x6d
003aa5f8 782b6a20 lq $t3, 27168($at)
003aa5fc 7e2b01f0 sq $t3, 496($s1)
003aa600 852b0044 lh $t3, 0x44($t1)
003aa604 26310200 addiu $s1, $s1, 0x200
003aa608 010b4021 addu $t0, $t0, $t3
003aa60c 0008443c dsll32 $t0, $t0, 0x10
003aa610 0008443f dsra32 $t0, $t0, 0x10
003aa614 00085900 sll $t3, $t0, 4
003aa618 00eb5825 or $t3, $a3, $t3
003aa61c acab0010 sw $t3, 0x10($a1)
003aa620 852b0040 lh $t3, 0x40($t1)
003aa624 010b5821 addu $t3, $t0, $t3
003aa628 000b5900 sll $t3, $t3, 4
003aa62c 00cb5825 or $t3, $a2, $t3
003aa630 1540ff3b bnez $t2, 0x3aa320
003aa634 acab0020 sw $t3, 0x20($a1)
003aa638 00041c3c dsll32 $v1, $a0, 0x10
003aa63c 00031c3f dsra32 $v1, $v1, 0x10
003aa640 0062082a slt $at, $v1, $v0
003aa644 10200020 beqz $at, 0x3aa6c8
003aa648 00000000 nop 
003aa64c 00000000 nop 
003aa650 3c01006d lui $at, 0x6d
003aa654 782a69f0 lq $t2, 27120($at)
003aa658 24830001 addiu $v1, $a0, 1
003aa65c 0003243c dsll32 $a0, $v1, 0x10
003aa660 0004243f dsra32 $a0, $a0, 0x10
003aa664 0082182a slt $v1, $a0, $v0
003aa668 7e2a0000 sq $t2, 0($s1)
003aa66c 3c01006d lui $at, 0x6d
003aa670 782a6a00 lq $t2, 27136($at)
003aa674 7e2a0010 sq $t2, 16($s1)
003aa678 3c01006d lui $at, 0x6d
003aa67c 782a6a10 lq $t2, 27152($at)
003aa680 7e2a0020 sq $t2, 32($s1)
003aa684 3c01006d lui $at, 0x6d
003aa688 782a6a20 lq $t2, 27168($at)
003aa68c 7e2a0030 sq $t2, 48($s1)
003aa690 852a0044 lh $t2, 0x44($t1)
003aa694 26310040 addiu $s1, $s1, 0x40
003aa698 010a4021 addu $t0, $t0, $t2
003aa69c 0008443c dsll32 $t0, $t0, 0x10
003aa6a0 0008443f dsra32 $t0, $t0, 0x10
003aa6a4 00085100 sll $t2, $t0, 4
003aa6a8 00ea5025 or $t2, $a3, $t2
003aa6ac acaa0010 sw $t2, 0x10($a1)
003aa6b0 852a0040 lh $t2, 0x40($t1)
003aa6b4 010a5021 addu $t2, $t0, $t2
003aa6b8 000a5100 sll $t2, $t2, 4
003aa6bc 00ca5025 or $t2, $a2, $t2
003aa6c0 1460ffe3 bnez $v1, 0x3aa650
003aa6c4 acaa0020 sw $t2, 0x20($a1)
003aa6c8 10000003 b 0x3aa6d8
003aa6cc 0220102d move $v0, $s1
003aa6d0 0c04f168 jal 0x13c5a0
003aa6d4 0000482d move $t1, $zero
003aa6d8 dfbf0050 ld $ra, 0x50($sp)
003aa6dc 7bb40040 lq $s4, 64($sp)
003aa6e0 7bb30030 lq $s3, 48($sp)
003aa6e4 7bb20020 lq $s2, 32($sp)
003aa6e8 7bb10010 lq $s1, 16($sp)
003aa6ec 7bb00000 lq $s0, 0($sp)
003aa6f0 03e00008 jr $ra
003aa6f4 27bd0060 addiu $sp, $sp, 0x60
003aa6f8 00000000 nop 
003aa6fc 00000000 nop 
