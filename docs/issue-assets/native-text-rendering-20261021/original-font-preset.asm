003aa8e0 0004363c dsll32 $a2, $a0, 0x18
003aa8e4 a3848a48 sb $a0, -0x75b8($gp)
003aa8e8 0006363f dsra32 $a2, $a2, 0x18
003aa8ec 3c030043 lui $v1, 0x43
003aa8f0 00062880 sll $a1, $a2, 2
003aa8f4 2463f540 addiu $v1, $v1, -0xac0
003aa8f8 00a62821 addu $a1, $a1, $a2
003aa8fc 24040001 addiu $a0, $zero, 1
003aa900 00052840 sll $a1, $a1, 1
003aa904 3c010047 lui $at, 0x47
003aa908 00a62821 addu $a1, $a1, $a2
003aa90c a424e378 sh $a0, -0x1c88($at)
003aa910 00052840 sll $a1, $a1, 1
003aa914 3c010047 lui $at, 0x47
003aa918 00652821 addu $a1, $v1, $a1
003aa91c 84a30000 lh $v1, ($a1)
003aa920 a423e368 sh $v1, -0x1c98($at)
003aa924 84a30002 lh $v1, 2($a1)
003aa928 3c010047 lui $at, 0x47
003aa92c a423e36a sh $v1, -0x1c96($at)
003aa930 84a30004 lh $v1, 4($a1)
003aa934 3c010047 lui $at, 0x47
003aa938 a423e36c sh $v1, -0x1c94($at)
003aa93c 84a30006 lh $v1, 6($a1)
003aa940 3c010047 lui $at, 0x47
003aa944 a423e36e sh $v1, -0x1c92($at)
003aa948 84a30008 lh $v1, 8($a1)
003aa94c 3c010047 lui $at, 0x47
003aa950 a423e370 sh $v1, -0x1c90($at)
003aa954 84a3000a lh $v1, 0xa($a1)
003aa958 3c010047 lui $at, 0x47
003aa95c a423e372 sh $v1, -0x1c8e($at)
003aa960 84a3000c lh $v1, 0xc($a1)
003aa964 3c010047 lui $at, 0x47
003aa968 a423e374 sh $v1, -0x1c8c($at)
003aa96c 84a3000e lh $v1, 0xe($a1)
003aa970 3c010047 lui $at, 0x47
003aa974 a423e376 sh $v1, -0x1c8a($at)
003aa978 84a30010 lh $v1, 0x10($a1)
003aa97c 3c010047 lui $at, 0x47
003aa980 a423e35c sh $v1, -0x1ca4($at)
003aa984 84a30012 lh $v1, 0x12($a1)
003aa988 3c010047 lui $at, 0x47
003aa98c a423e35e sh $v1, -0x1ca2($at)
003aa990 84a30014 lh $v1, 0x14($a1)
003aa994 3c010047 lui $at, 0x47
003aa998 a423e360 sh $v1, -0x1ca0($at)
003aa99c 3c010047 lui $at, 0x47
003aa9a0 a024e37b sb $a0, -0x1c85($at)
003aa9a4 3c010047 lui $at, 0x47
003aa9a8 a024e37c sb $a0, -0x1c84($at)
003aa9ac 3c010047 lui $at, 0x47
003aa9b0 a024e37d sb $a0, -0x1c83($at)
003aa9b4 3c010047 lui $at, 0x47
003aa9b8 a024e37e sb $a0, -0x1c82($at)
003aa9bc 3c010047 lui $at, 0x47
003aa9c0 03e00008 jr $ra
003aa9c4 a024e37f sb $a0, -0x1c81($at)
