003ab0b0 0004363c dsll32 $a2, $a0, 0x18
003ab0b4 a3848a48 sb $a0, -0x75b8($gp)
003ab0b8 0006363f dsra32 $a2, $a2, 0x18
003ab0bc 3c030043 lui $v1, 0x43
003ab0c0 00062880 sll $a1, $a2, 2
003ab0c4 2463fd70 addiu $v1, $v1, -0x290
003ab0c8 00a62821 addu $a1, $a1, $a2
003ab0cc 24040001 addiu $a0, $zero, 1
003ab0d0 00052840 sll $a1, $a1, 1
003ab0d4 3c010047 lui $at, 0x47
003ab0d8 00a62821 addu $a1, $a1, $a2
003ab0dc a424eb78 sh $a0, -0x1488($at)
003ab0e0 00052840 sll $a1, $a1, 1
003ab0e4 3c010047 lui $at, 0x47
003ab0e8 00652821 addu $a1, $v1, $a1
003ab0ec 84a30000 lh $v1, ($a1)
003ab0f0 a423eb68 sh $v1, -0x1498($at)
003ab0f4 84a30002 lh $v1, 2($a1)
003ab0f8 3c010047 lui $at, 0x47
003ab0fc a423eb6a sh $v1, -0x1496($at)
003ab100 84a30004 lh $v1, 4($a1)
003ab104 3c010047 lui $at, 0x47
003ab108 a423eb6c sh $v1, -0x1494($at)
003ab10c 84a30006 lh $v1, 6($a1)
003ab110 3c010047 lui $at, 0x47
003ab114 a423eb6e sh $v1, -0x1492($at)
003ab118 84a30008 lh $v1, 8($a1)
003ab11c 3c010047 lui $at, 0x47
003ab120 a423eb70 sh $v1, -0x1490($at)
003ab124 84a3000a lh $v1, 0xa($a1)
003ab128 3c010047 lui $at, 0x47
003ab12c a423eb72 sh $v1, -0x148e($at)
003ab130 84a3000c lh $v1, 0xc($a1)
003ab134 3c010047 lui $at, 0x47
003ab138 a423eb74 sh $v1, -0x148c($at)
003ab13c 84a3000e lh $v1, 0xe($a1)
003ab140 3c010047 lui $at, 0x47
003ab144 a423eb76 sh $v1, -0x148a($at)
003ab148 84a30010 lh $v1, 0x10($a1)
003ab14c 3c010047 lui $at, 0x47
003ab150 a423eb5c sh $v1, -0x14a4($at)
003ab154 84a30012 lh $v1, 0x12($a1)
003ab158 3c010047 lui $at, 0x47
003ab15c a423eb5e sh $v1, -0x14a2($at)
003ab160 84a30014 lh $v1, 0x14($a1)
003ab164 3c010047 lui $at, 0x47
003ab168 a423eb60 sh $v1, -0x14a0($at)
003ab16c 3c010047 lui $at, 0x47
003ab170 a024eb7b sb $a0, -0x1485($at)
003ab174 3c010047 lui $at, 0x47
003ab178 a024eb7c sb $a0, -0x1484($at)
003ab17c 3c010047 lui $at, 0x47
003ab180 a024eb7d sb $a0, -0x1483($at)
003ab184 3c010047 lui $at, 0x47
003ab188 a024eb7e sb $a0, -0x1482($at)
003ab18c 3c010047 lui $at, 0x47
003ab190 03e00008 jr $ra
003ab194 a024eb7f sb $a0, -0x1481($at)
