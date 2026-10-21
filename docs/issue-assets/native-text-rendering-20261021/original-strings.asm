001a0d88 0080382d move $a3, $a0
001a0d8c 00a74025 or $t0, $a1, $a3
001a0d90 31020007 andi $v0, $t0, 7
001a0d94 14400038 bnez $v0, 0x1a0e78
001a0d98 00e0182d move $v1, $a3
001a0d9c 3102000f andi $v0, $t0, 0xf
001a0da0 3c090101 lui $t1, 0x101
001a0da4 35290101 ori $t1, $t1, 0x101
001a0da8 00094c38 dsll $t1, $t1, 0x10
001a0dac 35290101 ori $t1, $t1, 0x101
001a0db0 00094c38 dsll $t1, $t1, 0x10
001a0db4 35290101 ori $t1, $t1, 0x101
001a0db8 3c048080 lui $a0, 0x8080
001a0dbc 34848080 ori $a0, $a0, 0x8080
001a0dc0 00042438 dsll $a0, $a0, 0x10
001a0dc4 34848080 ori $a0, $a0, 0x8080
001a0dc8 00042438 dsll $a0, $a0, 0x10
001a0dcc 34848080 ori $a0, $a0, 0x8080
001a0dd0 54400019 bnel $v0, $zero, 0x1a0e38
001a0dd4 dcaa0000 ld $t2, ($a1)
001a0dd8 71295389 .word 0x71295389 ; unresolved EE MMI
001a0ddc 78a90000 lq $t1, 0($a1)
001a0de0 70844389 .word 0x70844389 ; unresolved EE MMI
001a0de4 712a1248 .word 0x712a1248 ; unresolved EE MMI
001a0de8 70091ce9 .word 0x70091ce9 ; unresolved EE MMI
001a0dec 70431489 .word 0x70431489 ; unresolved EE MMI
001a0df0 70481489 .word 0x70481489 ; unresolved EE MMI
001a0df4 704923a9 .word 0x704923a9 ; unresolved EE MMI
001a0df8 00441825 or $v1, $v0, $a0
001a0dfc 1460001d bnez $v1, 0x1a0e74
001a0e00 00e0302d move $a2, $a3
001a0e04 7cc90000 sq $t1, 0($a2)
001a0e08 24a50010 addiu $a1, $a1, 0x10
001a0e0c 78a90000 lq $t1, 0($a1)
001a0e10 712a1248 .word 0x712a1248 ; unresolved EE MMI
001a0e14 70091ce9 .word 0x70091ce9 ; unresolved EE MMI
001a0e18 70431489 .word 0x70431489 ; unresolved EE MMI
001a0e1c 70481489 .word 0x70481489 ; unresolved EE MMI
001a0e20 704923a9 .word 0x704923a9 ; unresolved EE MMI
001a0e24 00441825 or $v1, $v0, $a0
001a0e28 1060fff6 beqz $v1, 0x1a0e04
001a0e2c 24c60010 addiu $a2, $a2, 0x10
001a0e30 10000011 b 0x1a0e78
001a0e34 00c0182d move $v1, $a2
001a0e38 0149102f dsubu $v0, $t2, $t1
001a0e3c 000a1827 nor $v1, $zero, $t2
001a0e40 00431024 and $v0, $v0, $v1
001a0e44 00441024 and $v0, $v0, $a0
001a0e48 1440000a bnez $v0, 0x1a0e74
001a0e4c 00e0302d move $a2, $a3
001a0e50 fcca0000 sd $t2, ($a2)
001a0e54 24a50008 addiu $a1, $a1, 8
001a0e58 dcaa0000 ld $t2, ($a1)
001a0e5c 000a1027 nor $v0, $zero, $t2
001a0e60 0149182f dsubu $v1, $t2, $t1
001a0e64 00621824 and $v1, $v1, $v0
001a0e68 00641824 and $v1, $v1, $a0
001a0e6c 1060fff8 beqz $v1, 0x1a0e50
001a0e70 24c60008 addiu $a2, $a2, 8
001a0e74 00c0182d move $v1, $a2
001a0e78 90a20000 lbu $v0, ($a1)
001a0e7c 24a50001 addiu $a1, $a1, 1
001a0e80 a0620000 sb $v0, ($v1)
001a0e84 00021600 sll $v0, $v0, 0x18
001a0e88 24630001 addiu $v1, $v1, 1
001a0e8c 1440fffa bnez $v0, 0x1a0e78
001a0e90 00000000 nop 
001a0e94 03e00008 jr $ra
001a0e98 00e0102d move $v0, $a3
001a0e9c 00000000 nop 
001a0ea0 30820007 andi $v0, $a0, 7
001a0ea4 14400043 bnez $v0, 0x1a0fb4
001a0ea8 0080382d move $a3, $a0
001a0eac 3083000f andi $v1, $a0, 0xf
001a0eb0 3c020101 lui $v0, 0x101
001a0eb4 34420101 ori $v0, $v0, 0x101
001a0eb8 00021438 dsll $v0, $v0, 0x10
001a0ebc 34420101 ori $v0, $v0, 0x101
001a0ec0 00021438 dsll $v0, $v0, 0x10
001a0ec4 34420101 ori $v0, $v0, 0x101
001a0ec8 1460001e bnez $v1, 0x1a0f44
001a0ecc 0080282d move $a1, $a0
001a0ed0 78a30000 lq $v1, 0($a1)
001a0ed4 70424389 .word 0x70424389 ; unresolved EE MMI
001a0ed8 3c048080 lui $a0, 0x8080
001a0edc 34848080 ori $a0, $a0, 0x8080
001a0ee0 00042438 dsll $a0, $a0, 0x10
001a0ee4 34848080 ori $a0, $a0, 0x8080
001a0ee8 00042438 dsll $a0, $a0, 0x10
001a0eec 34848080 ori $a0, $a0, 0x8080
001a0ef0 70681248 .word 0x70681248 ; unresolved EE MMI
001a0ef4 70031ce9 .word 0x70031ce9 ; unresolved EE MMI
001a0ef8 70844b89 .word 0x70844b89 ; unresolved EE MMI
001a0efc 70431489 .word 0x70431489 ; unresolved EE MMI
001a0f00 70491489 .word 0x70491489 ; unresolved EE MMI
001a0f04 70481ba9 .word 0x70481ba9 ; unresolved EE MMI
001a0f08 00623025 or $a2, $v1, $v0
001a0f0c 54c00029 bnel $a2, $zero, 0x1a0fb4
001a0f10 00a0202d move $a0, $a1
001a0f14 24a50010 addiu $a1, $a1, 0x10
001a0f18 78a20000 lq $v0, 0($a1)
001a0f1c 70021ce9 .word 0x70021ce9 ; unresolved EE MMI
001a0f20 70481248 .word 0x70481248 ; unresolved EE MMI
001a0f24 70431489 .word 0x70431489 ; unresolved EE MMI
001a0f28 70492489 .word 0x70492489 ; unresolved EE MMI
001a0f2c 70861ba9 .word 0x70861ba9 ; unresolved EE MMI
001a0f30 00641825 or $v1, $v1, $a0
001a0f34 5060fff8 beql $v1, $zero, 0x1a0f18
001a0f38 24a50010 addiu $a1, $a1, 0x10
001a0f3c 1000001d b 0x1a0fb4
001a0f40 00a0202d move $a0, $a1
001a0f44 dca30000 ld $v1, ($a1)
001a0f48 3c048080 lui $a0, 0x8080
001a0f4c 34848080 ori $a0, $a0, 0x8080
001a0f50 00042438 dsll $a0, $a0, 0x10
001a0f54 34848080 ori $a0, $a0, 0x8080
001a0f58 00042438 dsll $a0, $a0, 0x10
001a0f5c 34848080 ori $a0, $a0, 0x8080
001a0f60 0062102f dsubu $v0, $v1, $v0
001a0f64 00031827 nor $v1, $zero, $v1
001a0f68 00431024 and $v0, $v0, $v1
001a0f6c 00441024 and $v0, $v0, $a0
001a0f70 54400010 bnel $v0, $zero, 0x1a0fb4
001a0f74 00a0202d move $a0, $a1
001a0f78 3c060101 lui $a2, 0x101
001a0f7c 34c60101 ori $a2, $a2, 0x101
001a0f80 00063438 dsll $a2, $a2, 0x10
001a0f84 34c60101 ori $a2, $a2, 0x101
001a0f88 00063438 dsll $a2, $a2, 0x10
001a0f8c 34c60101 ori $a2, $a2, 0x101
001a0f90 24a50008 addiu $a1, $a1, 8
001a0f94 dca20000 ld $v0, ($a1)
001a0f98 00021827 nor $v1, $zero, $v0
001a0f9c 0046102f dsubu $v0, $v0, $a2
001a0fa0 00431024 and $v0, $v0, $v1
001a0fa4 00441024 and $v0, $v0, $a0
001a0fa8 5040fffa beql $v0, $zero, 0x1a0f94
001a0fac 24a50008 addiu $a1, $a1, 8
001a0fb0 00a0202d move $a0, $a1
001a0fb4 80820000 lb $v0, ($a0)
001a0fb8 00000000 nop 
001a0fbc 00000000 nop 
001a0fc0 00000000 nop 
001a0fc4 00000000 nop 
001a0fc8 5440fffa bnel $v0, $zero, 0x1a0fb4
001a0fcc 24840001 addiu $a0, $a0, 1
001a0fd0 03e00008 jr $ra
001a0fd4 00871023 subu $v0, $a0, $a3
