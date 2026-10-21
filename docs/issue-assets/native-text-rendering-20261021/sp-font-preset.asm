003d5db0 0004363c dsll32 $a2, $a0, 0x18
003d5db4 a3848b34 sb $a0, -0x74cc($gp)
003d5db8 0006363f dsra32 $a2, $a2, 0x18
003d5dbc 3c03004a lui $v1, 0x4a
003d5dc0 00062880 sll $a1, $a2, 2
003d5dc4 2463e190 addiu $v1, $v1, -0x1e70
003d5dc8 00a62821 addu $a1, $a1, $a2
003d5dcc 24040001 addiu $a0, $zero, 1
003d5dd0 00052840 sll $a1, $a1, 1
003d5dd4 3c01004f lui $at, 0x4f
003d5dd8 00a62821 addu $a1, $a1, $a2
003d5ddc a424d5f8 sh $a0, -0x2a08($at)
003d5de0 00052840 sll $a1, $a1, 1
003d5de4 3c01004f lui $at, 0x4f
003d5de8 00652821 addu $a1, $v1, $a1
003d5dec 84a30000 lh $v1, ($a1)
003d5df0 a423d5e8 sh $v1, -0x2a18($at)
003d5df4 84a30002 lh $v1, 2($a1)
003d5df8 3c01004f lui $at, 0x4f
003d5dfc a423d5ea sh $v1, -0x2a16($at)
003d5e00 84a30004 lh $v1, 4($a1)
003d5e04 3c01004f lui $at, 0x4f
003d5e08 a423d5ec sh $v1, -0x2a14($at)
003d5e0c 84a30006 lh $v1, 6($a1)
003d5e10 3c01004f lui $at, 0x4f
003d5e14 a423d5ee sh $v1, -0x2a12($at)
003d5e18 84a30008 lh $v1, 8($a1)
003d5e1c 3c01004f lui $at, 0x4f
003d5e20 a423d5f0 sh $v1, -0x2a10($at)
003d5e24 84a3000a lh $v1, 0xa($a1)
003d5e28 3c01004f lui $at, 0x4f
003d5e2c a423d5f2 sh $v1, -0x2a0e($at)
003d5e30 84a3000c lh $v1, 0xc($a1)
003d5e34 3c01004f lui $at, 0x4f
003d5e38 a423d5f4 sh $v1, -0x2a0c($at)
003d5e3c 84a3000e lh $v1, 0xe($a1)
003d5e40 3c01004f lui $at, 0x4f
003d5e44 a423d5f6 sh $v1, -0x2a0a($at)
003d5e48 84a30010 lh $v1, 0x10($a1)
003d5e4c 3c01004f lui $at, 0x4f
003d5e50 a423d5dc sh $v1, -0x2a24($at)
003d5e54 84a30012 lh $v1, 0x12($a1)
003d5e58 3c01004f lui $at, 0x4f
003d5e5c a423d5de sh $v1, -0x2a22($at)
003d5e60 84a30014 lh $v1, 0x14($a1)
003d5e64 3c01004f lui $at, 0x4f
003d5e68 a423d5e0 sh $v1, -0x2a20($at)
003d5e6c 3c01004f lui $at, 0x4f
003d5e70 a024d5fb sb $a0, -0x2a05($at)
003d5e74 3c01004f lui $at, 0x4f
003d5e78 a024d5fc sb $a0, -0x2a04($at)
003d5e7c 3c01004f lui $at, 0x4f
003d5e80 a024d5fd sb $a0, -0x2a03($at)
003d5e84 3c01004f lui $at, 0x4f
003d5e88 a024d5fe sb $a0, -0x2a02($at)
003d5e8c 3c01004f lui $at, 0x4f
003d5e90 03e00008 jr $ra
003d5e94 a024d5ff sb $a0, -0x2a01($at)
