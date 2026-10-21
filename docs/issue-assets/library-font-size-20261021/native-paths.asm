; Original SLPS_258.87 VA 0x139930..0x139A50
00139930 lui          $at, 0x47
00139934 lui          $v1, 0xff
00139938 sh           $zero, -0x1cbe($at)
0013993c ori          $a0, $v1, 0xffff
00139940 lui          $at, 0x47
00139944 addiu        $a2, $zero, 0x16
00139948 sh           $zero, -0x1cc0($at)
0013994c addiu        $a1, $zero, 0xb
00139950 lui          $at, 0x47
00139954 addiu        $v1, $zero, 0x12
00139958 sh           $a2, -0x1cbc($at)
0013995c lui          $at, 0x47
00139960 sh           $a1, -0x1cba($at)
00139964 lui          $at, 0x47
00139968 sh           $a2, -0x1cb8($at)
0013996c lui          $at, 0x47
00139970 sh           $a1, -0x1cb6($at)
00139974 lui          $at, 0x47
00139978 sh           $v1, -0x1ca4($at)
0013997c addiu        $v1, $zero, 0x10
00139980 lui          $at, 0x47
00139984 sh           $v1, -0x1ca0($at)
00139988 lui          $at, 0x47
0013998c lui          $v1, 0x8080
00139990 sh           $zero, -0x1cb4($at)
00139994 ori          $v1, $v1, 0x8080
00139998 lui          $at, 0x47
0013999c sw           $a0, -0x1cb0($at)
001399a0 lui          $at, 0x47
001399a4 sw           $a0, -0x1c9c($at)
001399a8 lui          $at, 0x47
001399ac sh           $a1, -0x1ca2($at)
001399b0 lui          $at, 0x47
001399b4 sh           $zero, -0x1c9e($at)
001399b8 lui          $at, 0x47
001399bc sb           $zero, -0x1c86($at)
001399c0 lui          $at, 0x47
001399c4 sw           $v1, -0x1cac($at)
001399c8 lui          $at, 0x47
001399cc sw           $v1, -0x1ca8($at)
001399d0 lui          $at, 0x47
001399d4 sb           $zero, -0x1c80($at)
001399d8 lui          $at, 0x47
001399dc sh           $zero, -0x1c88($at)
001399e0 lui          $at, 0x47
001399e4 sh           $a2, -0x1c98($at)
001399e8 lui          $at, 0x47
001399ec sh           $a1, -0x1c96($at)
001399f0 lui          $at, 0x47
001399f4 sh           $a2, -0x1c94($at)
001399f8 lui          $at, 0x47
001399fc sh           $a1, -0x1c92($at)
00139a00 lui          $at, 0x47
00139a04 sh           $a2, -0x1c90($at)
00139a08 lui          $at, 0x47
00139a0c sh           $a2, -0x1c8c($at)
00139a10 lui          $at, 0x47
00139a14 sh           $a1, -0x1c8e($at)
00139a18 lui          $at, 0x47
00139a1c sh           $a1, -0x1c8a($at)
00139a20 lui          $at, 0x47
00139a24 sb           $zero, -0x1c85($at)
00139a28 lui          $at, 0x47
00139a2c sb           $zero, -0x1c84($at)
00139a30 lui          $at, 0x47
00139a34 sb           $zero, -0x1c83($at)
00139a38 lui          $at, 0x47
00139a3c sb           $zero, -0x1c82($at)
00139a40 lui          $at, 0x47
00139a44 jr           $ra
00139a48 sb           $zero, -0x1c81($at)
00139a4c nop          
; Original SLPS_258.87 VA 0x139D50..0x139E70
00139d50 lui          $at, 0x47
00139d54 addiu        $v1, $zero, 1
00139d58 sh           $a0, -0x1c98($at)
00139d5c lui          $at, 0x47
00139d60 lb           $a0, 0x18($sp)
00139d64 sh           $a1, -0x1c96($at)
00139d68 lui          $at, 0x47
00139d6c lb           $a1, 0x10($sp)
00139d70 sh           $v1, -0x1c88($at)
00139d74 lui          $at, 0x47
00139d78 lb           $v1, 0x20($sp)
00139d7c sh           $a2, -0x1c94($at)
00139d80 lui          $at, 0x47
00139d84 lb           $a2, 8($sp)
00139d88 sh           $a3, -0x1c92($at)
00139d8c lui          $at, 0x47
00139d90 lb           $a3, ($sp)
00139d94 sh           $t0, -0x1c90($at)
00139d98 lui          $at, 0x47
00139d9c sh           $t1, -0x1c8e($at)
00139da0 lui          $at, 0x47
00139da4 sh           $t2, -0x1c8c($at)
00139da8 lui          $at, 0x47
00139dac sh           $t3, -0x1c8a($at)
00139db0 lui          $at, 0x47
00139db4 sb           $a3, -0x1c85($at)
00139db8 lui          $at, 0x47
00139dbc sb           $a2, -0x1c84($at)
00139dc0 lui          $at, 0x47
00139dc4 sb           $a1, -0x1c83($at)
00139dc8 lui          $at, 0x47
00139dcc sb           $a0, -0x1c82($at)
00139dd0 lui          $at, 0x47
00139dd4 jr           $ra
00139dd8 sb           $v1, -0x1c81($at)
00139ddc nop          
00139de0 lui          $at, 0x47
00139de4 sh           $zero, -0x1c88($at)
00139de8 lui          $at, 0x47
00139dec sb           $zero, -0x1c85($at)
00139df0 lui          $at, 0x47
00139df4 sb           $zero, -0x1c84($at)
00139df8 lui          $at, 0x47
00139dfc sb           $zero, -0x1c83($at)
00139e00 lui          $at, 0x47
00139e04 sb           $zero, -0x1c82($at)
00139e08 lui          $at, 0x47
00139e0c jr           $ra
00139e10 sb           $zero, -0x1c81($at)
00139e14 nop          
00139e18 nop          
00139e1c nop          
00139e20 lui          $at, 0x47
00139e24 sh           $a0, -0x1cc0($at)
00139e28 lui          $at, 0x47
00139e2c jr           $ra
00139e30 sh           $a1, -0x1cbe($at)
00139e34 nop          
00139e38 nop          
00139e3c nop          
00139e40 lui          $at, 0x47
00139e44 sh           $a0, -0x1cbc($at)
00139e48 lui          $at, 0x47
00139e4c sh           $a1, -0x1cba($at)
00139e50 lui          $at, 0x47
00139e54 sh           $a2, -0x1cb8($at)
00139e58 lui          $at, 0x47
00139e5c jr           $ra
00139e60 sh           $a3, -0x1cb6($at)
00139e64 nop          
00139e68 nop          
00139e6c nop          
; Original SLPS_258.87 VA 0x13A340..0x13A390
0013a340 lui          $at, 0x47
0013a344 lw           $a0, -0x1c78($at)
0013a348 addiu        $v0, $zero, 0x140
0013a34c lhu          $a1, ($s1)
0013a350 lw           $v1, 0x14($s1)
0013a354 lui          $at, 0x7000
0013a358 sll          $a1, $a1, 5
0013a35c sw           $v1, 0x34($at)
0013a360 addu         $s0, $a0, $a1
0013a364 lui          $at, 0x7000
0013a368 sh           $v0, 0x40($at)
0013a36c lw           $v0, 0x18($s1)
0013a370 lui          $at, 0x7000
0013a374 sw           $v0, 0x38($at)
0013a378 lui          $at, 0x7000
0013a37c sw           $zero, 0x48($at)
0013a380 lh           $v0, 0x48($s1)
0013a384 lui          $at, 0x7000
0013a388 sw           $v0, 0x68($at)
0013a38c nop          
; Original SLPS_258.87 VA 0x13A470..0x13A4CC
0013a470 lbu          $v0, ($s4)
0013a474 lui          $at, 0x7000
0013a478 sh           $v0, 0x14($s1)
0013a47c addiu        $s4, $s4, 1
0013a480 sh           $v0, 0x34($at)
0013a484 b            0x13a390
0013a488 sh           $zero, 0x48($s1)
0013a48c nop          
0013a490 lbu          $v0, ($s4)
0013a494 lui          $at, 0x7000
0013a498 sh           $v0, 0x16($s1)
0013a49c addiu        $s4, $s4, 1
0013a4a0 lh           $v0, 0x16($s1)
0013a4a4 sh           $v0, 0x36($at)
0013a4a8 b            0x13a390
0013a4ac sh           $zero, 0x48($s1)
0013a4b0 lbu          $v0, ($s4)
0013a4b4 lui          $at, 0x7000
0013a4b8 sh           $v0, 0x18($s1)
0013a4bc addiu        $s4, $s4, 1
0013a4c0 sh           $v0, 0x38($at)
0013a4c4 b            0x13a390
0013a4c8 sh           $zero, 0x48($s1)
; Original SLPS_258.87 VA 0x13A618..0x13A7A0
0013a618 lw           $v1, 0x18($s1)
0013a61c lui          $at, 0x7000
0013a620 sw           $v1, 0x38($at)
0013a624 lh           $v1, 0x48($s1)
0013a628 beqz         $v1, 0x13a7a0
0013a62c andi         $v0, $v0, 0xffff
0013a630 lui          $at, 0x7000
0013a634 andi         $a0, $v0, 0xffff
0013a638 sw           $zero, 0x50($at)
0013a63c ori          $at, $zero, 0x8492
0013a640 slt          $at, $a0, $at
0013a644 beqz         $at, 0x13a758
0013a648 nop          
0013a64c lb           $v1, 0x4f($s1)
0013a650 beqz         $v1, 0x13a680
0013a654 ori          $at, $zero, 0x829f
0013a658 slt          $at, $a0, $at
0013a65c beqz         $at, 0x13a680
0013a660 ori          $v1, $zero, 0x8140
0013a664 slt          $v1, $a0, $v1
0013a668 bnez         $v1, 0x13a680
0013a66c nop          
0013a670 addiu        $v1, $zero, 1
0013a674 lui          $at, 0x7000
0013a678 b            0x13a758
0013a67c sw           $v1, 0x50($at)
0013a680 lb           $v1, 0x4e($s1)
0013a684 beqz         $v1, 0x13a6b8
0013a688 ori          $at, $zero, 0x8492
0013a68c slt          $at, $a0, $at
0013a690 beqz         $at, 0x13a6b8
0013a694 ori          $v1, $zero, 0x8340
0013a698 slt          $v1, $a0, $v1
0013a69c bnez         $v1, 0x13a6b8
0013a6a0 nop          
0013a6a4 addiu        $v1, $zero, 1
0013a6a8 lui          $at, 0x7000
0013a6ac b            0x13a758
0013a6b0 sw           $v1, 0x50($at)
0013a6b4 nop          
0013a6b8 lb           $v1, 0x4b($s1)
0013a6bc beqz         $v1, 0x13a6f0
0013a6c0 ori          $at, $zero, 0x827a
0013a6c4 slt          $at, $a0, $at
0013a6c8 beqz         $at, 0x13a6f0
0013a6cc ori          $v1, $zero, 0x8260
0013a6d0 slt          $v1, $a0, $v1
0013a6d4 bnez         $v1, 0x13a6f0
0013a6d8 nop          
0013a6dc addiu        $v1, $zero, 1
0013a6e0 lui          $at, 0x7000
0013a6e4 b            0x13a758
0013a6e8 sw           $v1, 0x50($at)
0013a6ec nop          
0013a6f0 lb           $v1, 0x4d($s1)
0013a6f4 beqz         $v1, 0x13a728
0013a6f8 ori          $at, $zero, 0x82f2
0013a6fc slt          $at, $a0, $at
0013a700 beqz         $at, 0x13a728
0013a704 ori          $v1, $zero, 0x829f
0013a708 slt          $v1, $a0, $v1
0013a70c bnez         $v1, 0x13a728
0013a710 nop          
0013a714 addiu        $v1, $zero, 1
0013a718 lui          $at, 0x7000
0013a71c b            0x13a758
0013a720 sw           $v1, 0x50($at)
0013a724 nop          
0013a728 lb           $v1, 0x4c($s1)
0013a72c beqz         $v1, 0x13a758
0013a730 ori          $at, $zero, 0x829b
0013a734 slt          $at, $a0, $at
0013a738 beqz         $at, 0x13a758
0013a73c ori          $v1, $zero, 0x8281
0013a740 slt          $v1, $a0, $v1
0013a744 bnez         $v1, 0x13a758
0013a748 nop          
0013a74c addiu        $v1, $zero, 1
0013a750 lui          $at, 0x7000
0013a754 sw           $v1, 0x50($at)
0013a758 lui          $at, 0x7000
0013a75c lw           $v1, 0x50($at)
0013a760 beqz         $v1, 0x13a788
0013a764 nop          
0013a768 lw           $v1, 0x40($s1)
0013a76c lui          $at, 0x7000
0013a770 sw           $v1, 0x3c($at)
0013a774 lw           $v1, 0x44($s1)
0013a778 lui          $at, 0x7000
0013a77c b            0x13a7a0
0013a780 sw           $v1, 0x38($at)
0013a784 nop          
0013a788 lw           $v1, 0x38($s1)
0013a78c lui          $at, 0x7000
0013a790 sw           $v1, 0x3c($at)
0013a794 lw           $v1, 0x3c($s1)
0013a798 lui          $at, 0x7000
0013a79c sw           $v1, 0x38($at)
; Original SLPS_258.87 VA 0x13AC58..0x13AC68
0013ac58 lui          $at, 0x7000
0013ac5c lw           $v1, 0x68($at)
0013ac60 move         $v0, $s3
0013ac64 sh           $v1, 0x48($s1)
; Original SLPS_258.87 VA 0x220DB0..0x220E44
00220db0 addiu        $sp, $sp, -0x90
00220db4 addiu        $v0, $zero, 1
00220db8 sd           $ra, 0x80($sp)
00220dbc dps.w.ph     $ac0, $sp, $s4
00220dc0 .byte        0x60, 0x00, 0xb3, 0x7f
00220dc4 move         $s4, $a0
00220dc8 subu.qb      $zero, $sp, $s2
00220dcc move         $s3, $a1
00220dd0 ext          $s1, $sp, 1, 1
00220dd4 move         $s2, $a2
00220dd8 dpa.w.ph     $ac0, $sp, $s0
00220ddc move         $s1, $a3
00220de0 sd           $v0, ($sp)
00220de4 move         $s0, $t0
00220de8 sd           $v0, 8($sp)
00220dec sd           $v0, 0x10($sp)
00220df0 sd           $v0, 0x18($sp)
00220df4 sd           $v0, 0x20($sp)
00220df8 lb           $a0, 0xe($t0)
00220dfc lb           $a1, 0xf($t0)
00220e00 lb           $a2, 0x10($t0)
00220e04 lb           $a3, 0x11($t0)
00220e08 lb           $t2, 0x14($s0)
00220e0c lb           $t3, 0x15($s0)
00220e10 lb           $t0, 0x12($t0)
00220e14 jal          0x139d50
00220e18 lb           $t1, 0x13($s0)
00220e1c lb           $a3, ($s0)
00220e20 dsll32       $a0, $s4, 0x10
00220e24 lw           $a2, 0x18($s0)
00220e28 dsll32       $a1, $s3, 0x10
00220e2c dsra32       $a0, $a0, 0x10
00220e30 jal          0x2254d0
00220e34 dsra32       $a1, $a1, 0x10
00220e38 move         $a0, $s2
00220e3c jal          0x225290
00220e40 move         $a1, $s1
; Original SLPS_258.87 VA 0x221198..0x22126C
00221198 lb           $s7, 0x11($s4)
0022119c subu         $v0, $a2, $s5
002211a0 move         $s0, $a0
002211a4 addiu        $s3, $v0, 1
002211a8 move         $s1, $zero
002211ac sw           $zero, 0xac($sp)
002211b0 sw           $zero, 0xa8($sp)
002211b4 lh           $fp, 2($s4)
002211b8 lh           $s2, 4($s4)
002211bc nop          
002211c0 move         $a1, $s5
002211c4 move         $a0, $s0
002211c8 addiu        $a2, $sp, 0xac
002211cc jal          0x221030
002211d0 addiu        $a3, $sp, 0xa8
002211d4 beqz         $v0, 0x221270
002211d8 nop          
002211dc lw           $v0, 0xac($sp)
002211e0 lui          $a0, 0x5a
002211e4 lw           $a2, 0xa8($sp)
002211e8 addiu        $a0, $a0, 0x4840
002211ec move         $s5, $zero
002211f0 jal          0x1a1190
002211f4 addu         $a1, $s0, $v0
002211f8 lw           $v0, 0xa8($sp)
002211fc lui          $a2, 0x5a
00221200 addiu        $a2, $a2, 0x4840
00221204 dsll32       $a0, $fp, 0x10
00221208 dsll32       $a1, $s2, 0x10
0022120c dsra32       $a0, $a0, 0x10
00221210 dsra32       $a1, $a1, 0x10
00221214 move         $a3, $s6
00221218 move         $t0, $s4
0022121c addu         $v0, $a2, $v0
00221220 jal          0x220db0
00221224 sb           $zero, ($v0)
00221228 lw           $v1, 0xac($sp)
0022122c addiu        $s3, $s3, -1
00221230 lw           $v0, 0xa8($sp)
00221234 addu         $s0, $s0, $v1
00221238 blez         $s3, 0x221250
0022123c addu         $s0, $s0, $v0
00221240 lb           $v0, ($s0)
00221244 bnez         $v0, 0x221258
00221248 nop          
0022124c nop          
00221250 b            0x221260
00221254 daddiu       $s1, $zero, 1
00221258 addiu        $s0, $s0, 1
0022125c addu         $s2, $s2, $s7
00221260 andi         $v0, $s1, 0xff
00221264 beqz         $v0, 0x2211c0
00221268 nop          
; Original SLPS_258.87 VA 0x20EE6C..0x20EE9C
0020ee6c jal          0x20e360
0020ee70 move         $s0, $v0
0020ee74 jal          0x2101a0
0020ee78 move         $s3, $v0
0020ee7c jal          0x210220
0020ee80 move         $s2, $v0
0020ee84 move         $a0, $s3
0020ee88 move         $a2, $s2
0020ee8c move         $t0, $v0
0020ee90 move         $a1, $zero
0020ee94 jal          0x20e1b0
0020ee98 addiu        $a3, $zero, 5
; Original SLPS_258.87 VA 0x20E68C..0x20E6C0
0020e68c nop          
0020e690 jal          0x20e360
0020e694 move         $s0, $v0
0020e698 jal          0x210140
0020e69c move         $s3, $v0
0020e6a0 jal          0x210210
0020e6a4 move         $s2, $v0
0020e6a8 move         $a0, $s3
0020e6ac move         $a2, $s2
0020e6b0 move         $t0, $v0
0020e6b4 move         $a1, $zero
0020e6b8 jal          0x20e1b0
0020e6bc addiu        $a3, $zero, 9
; Original SLPS_258.87 VA 0x20E968..0x20E998
0020e968 jal          0x20e360
0020e96c move         $s5, $v0
0020e970 jal          0x2100a0
0020e974 move         $s1, $v0
0020e978 jal          0x210200
0020e97c move         $s0, $v0
0020e980 move         $a0, $s1
0020e984 move         $a2, $s0
0020e988 move         $t0, $v0
0020e98c move         $a1, $zero
0020e990 jal          0x20e1b0
0020e994 addiu        $a3, $zero, 5
; Original SLPS_258.87 VA 0x2100A0..0x2100B0
002100a0 lui          $v0, 0x42
002100a4 jr           $ra
002100a8 addiu        $v0, $v0, -0x1120
002100ac nop          
; Original SLPS_258.87 VA 0x210140..0x210150
00210140 lui          $v0, 0x42
00210144 jr           $ra
00210148 addiu        $v0, $v0, -0xfe0
0021014c nop          
; Original SLPS_258.87 VA 0x2101A0..0x2101B0
002101a0 lui          $v0, 0x42
002101a4 jr           $ra
002101a8 addiu        $v0, $v0, -0xf20
002101ac nop          
; Original SLPS_258.87 VA 0x2098F0..0x209904
002098f0 jal          0x20b920
002098f4 nop          
002098f8 move         $a0, $s0
002098fc jal          0x2097c0
00209900 move         $a1, $v0
; Original SLPS_258.87 VA 0x20B920..0x20B930
0020b920 lui          $v0, 0x42
0020b924 jr           $ra
0020b928 addiu        $v0, $v0, -0x18d0
0020b92c nop          
; Original SLPS_258.87 VA 0x209740..0x209768
00209740 lui          $a1, 0x5a
00209744 lui          $at, 0x5a
00209748 move         $t1, $s0
0020974c move         $a0, $s1
00209750 addiu        $a1, $a1, 0x4140
00209754 addiu        $a2, $sp, 0x60
00209758 addiu        $a3, $s2, 0x24
0020975c addiu        $t0, $sp, 0x40
00209760 jal          0x2212b0
00209764 sw           $zero, 0x415c($at)
; Original SLPS_258.87 VA 0x2214D0..0x22153C
002214d0 lbu          $v0, 0xd0($sp)
002214d4 beqz         $v0, 0x221518
002214d8 nop          
002214dc lw           $v0, 0xe0($sp)
002214e0 addiu        $v1, $zero, 1
002214e4 bne          $v0, $v1, 0x221518
002214e8 nop          
002214ec lw           $t0, 0x100($sp)
002214f0 dsll32       $a0, $s4, 0x10
002214f4 dsll32       $a1, $s3, 0x10
002214f8 dsra32       $a0, $a0, 0x10
002214fc move         $a2, $s1
00221500 dsra32       $a1, $a1, 0x10
00221504 jal          0x220db0
00221508 move         $a3, $s7
0022150c b            0x221658
00221510 nop          
00221514 nop          
00221518 lw           $t0, 0x108($sp)
0022151c dsll32       $a0, $s4, 0x10
00221520 dsll32       $a1, $s3, 0x10
00221524 dsra32       $a0, $a0, 0x10
00221528 move         $a2, $s1
0022152c dsra32       $a1, $a1, 0x10
00221530 jal          0x220db0
00221534 move         $a3, $s7
00221538 b            0x221658
