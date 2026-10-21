; placeholder_number 003aa700..003aacf8
003aa700 27bdff60 addiu $sp, $sp, -0xa0
003aa704 ffbf0090 sd $ra, 0x90($sp)
003aa708 7fbe0080 sq $fp, 128($sp)
003aa70c 7fb70070 sq $s7, 112($sp)
003aa710 00e0f02d move $fp, $a3
003aa714 7fb60060 sq $s6, 96($sp)
003aa718 0140b82d move $s7, $t2
003aa71c 7fb50050 sq $s5, 80($sp)
003aa720 0100b02d move $s6, $t0
003aa724 7fb40040 sq $s4, 64($sp)
003aa728 0120a82d move $s5, $t1
003aa72c 7fb30030 sq $s3, 48($sp)
003aa730 7fb20020 sq $s2, 32($sp)
003aa734 00a0982d move $s3, $a1
003aa738 7fb10010 sq $s1, 16($sp)
003aa73c 7fb00000 sq $s0, 0($sp)
003aa740 0080802d move $s0, $a0
003aa744 0601015e bgez $s0, 0x3aacc0
003aa748 00c0882d move $s1, $a2
003aa74c 3c010043 lui $at, 0x43
003aa750 8c22fbb8 lw $v0, -0x448($at)
003aa754 10400006 beqz $v0, 0x3aa770
003aa758 00000000 nop 
003aa75c 0c0ea800 jal 0x3aa000
003aa760 00000000 nop 
003aa764 3c010043 lui $at, 0x43
003aa768 ac20fbb8 sw $zero, -0x448($at)
003aa76c 00000000 nop 
003aa770 00108023 negu $s0, $s0
003aa774 34018000 ori $at, $zero, 0x8000
003aa778 3c140047 lui $s4, 0x47
003aa77c 0201082a slt $at, $s0, $at
003aa780 14200003 bnez $at, 0x3aa790
003aa784 2694eb30 addiu $s4, $s4, -0x14d0
003aa788 24107fff addiu $s0, $zero, 0x7fff
003aa78c 00000000 nop 
003aa790 0011143c dsll32 $v0, $s1, 0x10
003aa794 0002143f dsra32 $v0, $v0, 0x10
003aa798 24430800 addiu $v1, $v0, 0x800
003aa79c 8682002e lh $v0, 0x2e($s4)
003aa7a0 00039500 sll $s2, $v1, 0x14
003aa7a4 00621021 addu $v0, $v1, $v0
003aa7a8 13c00011 beqz $fp, 0x3aa7f0
003aa7ac 00028d00 sll $s1, $v0, 0x14
003aa7b0 3c010047 lui $at, 0x47
003aa7b4 86850030 lh $a1, 0x30($s4)
003aa7b8 8423eb5c lh $v1, -0x14a4($at)
003aa7bc 0013143c dsll32 $v0, $s3, 0x10
003aa7c0 0002143f dsra32 $v0, $v0, 0x10
003aa7c4 24440800 addiu $a0, $v0, 0x800
003aa7c8 00b02818 mult $a1, $a1, $s0
003aa7cc 3c010047 lui $at, 0x47
003aa7d0 8422eb60 lh $v0, -0x14a0($at)
003aa7d4 00852023 subu $a0, $a0, $a1
003aa7d8 00831823 subu $v1, $a0, $v1
003aa7dc 00431021 addu $v0, $v0, $v1
003aa7e0 00029c3c dsll32 $s3, $v0, 0x10
003aa7e4 10000008 b 0x3aa808
003aa7e8 00139c3f dsra32 $s3, $s3, 0x10
003aa7ec 00000000 nop 
003aa7f0 0013143c dsll32 $v0, $s3, 0x10
003aa7f4 0002143f dsra32 $v0, $v0, 0x10
003aa7f8 24420800 addiu $v0, $v0, 0x800
003aa7fc 00029c3c dsll32 $s3, $v0, 0x10
003aa800 00139c3f dsra32 $s3, $s3, 0x10
003aa804 00000000 nop 
003aa808 00171e3c dsll32 $v1, $s7, 0x18
003aa80c 00031e3f dsra32 $v1, $v1, 0x18
003aa810 2402ffff addiu $v0, $zero, -1
003aa814 10620004 beq $v1, $v0, 0x3aa828
003aa818 02e0202d move $a0, $s7
003aa81c 0c0eab40 jal 0x3aad00
003aa820 00000000 nop 
003aa824 00000000 nop 
003aa828 3c01006d lui $at, 0x6d
003aa82c 78276890 lq $a3, 26768($at)
003aa830 26027fff addiu $v0, $s0, 0x7fff
003aa834 00132c3c dsll32 $a1, $s3, 0x10
003aa838 3c04006d lui $a0, 0x6d
003aa83c 24460001 addiu $a2, $v0, 1
003aa840 00052c3f dsra32 $a1, $a1, 0x10
003aa844 00051100 sll $v0, $a1, 4
003aa848 24846930 addiu $a0, $a0, 0x6930
003aa84c 02421025 or $v0, $s2, $v0
003aa850 0000182d move $v1, $zero
003aa854 7ec70000 sq $a3, 0($s6)
003aa858 3c01006d lui $at, 0x6d
003aa85c 782768a0 lq $a3, 26784($at)
003aa860 7ec70010 sq $a3, 16($s6)
003aa864 3c01006d lui $at, 0x6d
003aa868 782768b0 lq $a3, 26800($at)
003aa86c 7ec70020 sq $a3, 32($s6)
003aa870 3c01006d lui $at, 0x6d
003aa874 782768c0 lq $a3, 26816($at)
003aa878 7ec70030 sq $a3, 48($s6)
003aa87c 3c01006d lui $at, 0x6d
003aa880 782768d0 lq $a3, 26832($at)
003aa884 7ec70040 sq $a3, 64($s6)
003aa888 3c01006d lui $at, 0x6d
003aa88c 782768e0 lq $a3, 26848($at)
003aa890 7ec70050 sq $a3, 80($s6)
003aa894 3c01006d lui $at, 0x6d
003aa898 782768f0 lq $a3, 26864($at)
003aa89c 7ec70060 sq $a3, 96($s6)
003aa8a0 3c01006d lui $at, 0x6d
003aa8a4 78276900 lq $a3, 26880($at)
003aa8a8 7ec70070 sq $a3, 112($s6)
003aa8ac 3c01006d lui $at, 0x6d
003aa8b0 a4266910 sh $a2, 0x6910($at)
003aa8b4 86860032 lh $a2, 0x32($s4)
003aa8b8 3c01006d lui $at, 0x6d
003aa8bc a026692f sb $a2, 0x692f($at)
003aa8c0 8e860024 lw $a2, 0x24($s4)
003aa8c4 3c01006d lui $at, 0x6d
003aa8c8 ac860000 sw $a2, ($a0)
003aa8cc ac820010 sw $v0, 0x10($a0)
003aa8d0 ac950014 sw $s5, 0x14($a0)
003aa8d4 8682002c lh $v0, 0x2c($s4)
003aa8d8 00a21021 addu $v0, $a1, $v0
003aa8dc 00021100 sll $v0, $v0, 4
003aa8e0 02221025 or $v0, $s1, $v0
003aa8e4 ac820020 sw $v0, 0x20($a0)
003aa8e8 ac950024 sw $s5, 0x24($a0)
003aa8ec 78226910 lq $v0, 26896($at)
003aa8f0 7ec20080 sq $v0, 128($s6)
003aa8f4 0010082a slt $at, $zero, $s0
003aa8f8 102000ef beqz $at, 0x3aacb8
003aa8fc 26d60090 addiu $s6, $s6, 0x90
003aa900 2a010009 slti $at, $s0, 9
003aa904 142000c8 bnez $at, 0x3aac28
003aa908 2602fff8 addiu $v0, $s0, -8
003aa90c 00000000 nop 
003aa910 3c01006d lui $at, 0x6d
003aa914 78266920 lq $a2, 26912($at)
003aa918 24630008 addiu $v1, $v1, 8
003aa91c 00031c3c dsll32 $v1, $v1, 0x10
003aa920 00031c3f dsra32 $v1, $v1, 0x10
003aa924 0062282a slt $a1, $v1, $v0
003aa928 7ec60000 sq $a2, 0($s6)
003aa92c 3c01006d lui $at, 0x6d
003aa930 78266930 lq $a2, 26928($at)
003aa934 7ec60010 sq $a2, 16($s6)
003aa938 3c01006d lui $at, 0x6d
003aa93c 78266940 lq $a2, 26944($at)
003aa940 7ec60020 sq $a2, 32($s6)
003aa944 3c01006d lui $at, 0x6d
003aa948 78266950 lq $a2, 26960($at)
003aa94c 7ec60030 sq $a2, 48($s6)
003aa950 3c01006d lui $at, 0x6d
003aa954 86860030 lh $a2, 0x30($s4)
003aa958 02663021 addu $a2, $s3, $a2
003aa95c 00069c3c dsll32 $s3, $a2, 0x10
003aa960 00139c3f dsra32 $s3, $s3, 0x10
003aa964 00133100 sll $a2, $s3, 4
003aa968 02463025 or $a2, $s2, $a2
003aa96c ac860010 sw $a2, 0x10($a0)
003aa970 8686002c lh $a2, 0x2c($s4)
003aa974 02663021 addu $a2, $s3, $a2
003aa978 00063100 sll $a2, $a2, 4
003aa97c 02263025 or $a2, $s1, $a2
003aa980 ac860020 sw $a2, 0x20($a0)
003aa984 78266920 lq $a2, 26912($at)
003aa988 7ec60040 sq $a2, 64($s6)
003aa98c 3c01006d lui $at, 0x6d
003aa990 78266930 lq $a2, 26928($at)
003aa994 7ec60050 sq $a2, 80($s6)
003aa998 3c01006d lui $at, 0x6d
003aa99c 78266940 lq $a2, 26944($at)
003aa9a0 7ec60060 sq $a2, 96($s6)
003aa9a4 3c01006d lui $at, 0x6d
003aa9a8 78266950 lq $a2, 26960($at)
003aa9ac 7ec60070 sq $a2, 112($s6)
003aa9b0 3c01006d lui $at, 0x6d
003aa9b4 86860030 lh $a2, 0x30($s4)
003aa9b8 02663021 addu $a2, $s3, $a2
003aa9bc 00069c3c dsll32 $s3, $a2, 0x10
003aa9c0 00139c3f dsra32 $s3, $s3, 0x10
003aa9c4 00133100 sll $a2, $s3, 4
003aa9c8 02463025 or $a2, $s2, $a2
003aa9cc ac860010 sw $a2, 0x10($a0)
003aa9d0 8686002c lh $a2, 0x2c($s4)
003aa9d4 02663021 addu $a2, $s3, $a2
003aa9d8 00063100 sll $a2, $a2, 4
003aa9dc 02263025 or $a2, $s1, $a2
003aa9e0 ac860020 sw $a2, 0x20($a0)
003aa9e4 78266920 lq $a2, 26912($at)
003aa9e8 7ec60080 sq $a2, 128($s6)
003aa9ec 3c01006d lui $at, 0x6d
003aa9f0 78266930 lq $a2, 26928($at)
003aa9f4 7ec60090 sq $a2, 144($s6)
003aa9f8 3c01006d lui $at, 0x6d
003aa9fc 78266940 lq $a2, 26944($at)
003aaa00 7ec600a0 sq $a2, 160($s6)
003aaa04 3c01006d lui $at, 0x6d
003aaa08 78266950 lq $a2, 26960($at)
003aaa0c 7ec600b0 sq $a2, 176($s6)
003aaa10 3c01006d lui $at, 0x6d
003aaa14 86860030 lh $a2, 0x30($s4)
003aaa18 02663021 addu $a2, $s3, $a2
003aaa1c 00069c3c dsll32 $s3, $a2, 0x10
003aaa20 00139c3f dsra32 $s3, $s3, 0x10
003aaa24 00133100 sll $a2, $s3, 4
003aaa28 02463025 or $a2, $s2, $a2
003aaa2c ac860010 sw $a2, 0x10($a0)
003aaa30 8686002c lh $a2, 0x2c($s4)
003aaa34 02663021 addu $a2, $s3, $a2
003aaa38 00063100 sll $a2, $a2, 4
003aaa3c 02263025 or $a2, $s1, $a2
003aaa40 ac860020 sw $a2, 0x20($a0)
003aaa44 78266920 lq $a2, 26912($at)
003aaa48 7ec600c0 sq $a2, 192($s6)
003aaa4c 3c01006d lui $at, 0x6d
003aaa50 78266930 lq $a2, 26928($at)
003aaa54 7ec600d0 sq $a2, 208($s6)
003aaa58 3c01006d lui $at, 0x6d
003aaa5c 78266940 lq $a2, 26944($at)
003aaa60 7ec600e0 sq $a2, 224($s6)
003aaa64 3c01006d lui $at, 0x6d
003aaa68 78266950 lq $a2, 26960($at)
003aaa6c 7ec600f0 sq $a2, 240($s6)
003aaa70 3c01006d lui $at, 0x6d
003aaa74 86860030 lh $a2, 0x30($s4)
003aaa78 02663021 addu $a2, $s3, $a2
003aaa7c 00069c3c dsll32 $s3, $a2, 0x10
003aaa80 00139c3f dsra32 $s3, $s3, 0x10
003aaa84 00133100 sll $a2, $s3, 4
003aaa88 02463025 or $a2, $s2, $a2
003aaa8c ac860010 sw $a2, 0x10($a0)
003aaa90 8686002c lh $a2, 0x2c($s4)
003aaa94 02663021 addu $a2, $s3, $a2
003aaa98 00063100 sll $a2, $a2, 4
003aaa9c 02263025 or $a2, $s1, $a2
003aaaa0 ac860020 sw $a2, 0x20($a0)
003aaaa4 78266920 lq $a2, 26912($at)
003aaaa8 7ec60100 sq $a2, 256($s6)
003aaaac 3c01006d lui $at, 0x6d
003aaab0 78266930 lq $a2, 26928($at)
003aaab4 7ec60110 sq $a2, 272($s6)
003aaab8 3c01006d lui $at, 0x6d
003aaabc 78266940 lq $a2, 26944($at)
003aaac0 7ec60120 sq $a2, 288($s6)
003aaac4 3c01006d lui $at, 0x6d
003aaac8 78266950 lq $a2, 26960($at)
003aaacc 7ec60130 sq $a2, 304($s6)
003aaad0 3c01006d lui $at, 0x6d
003aaad4 86860030 lh $a2, 0x30($s4)
003aaad8 02663021 addu $a2, $s3, $a2
003aaadc 00069c3c dsll32 $s3, $a2, 0x10
003aaae0 00139c3f dsra32 $s3, $s3, 0x10
003aaae4 00133100 sll $a2, $s3, 4
003aaae8 02463025 or $a2, $s2, $a2
003aaaec ac860010 sw $a2, 0x10($a0)
003aaaf0 8686002c lh $a2, 0x2c($s4)
003aaaf4 02663021 addu $a2, $s3, $a2
003aaaf8 00063100 sll $a2, $a2, 4
003aaafc 02263025 or $a2, $s1, $a2
003aab00 ac860020 sw $a2, 0x20($a0)
003aab04 78266920 lq $a2, 26912($at)
003aab08 7ec60140 sq $a2, 320($s6)
003aab0c 3c01006d lui $at, 0x6d
003aab10 78266930 lq $a2, 26928($at)
003aab14 7ec60150 sq $a2, 336($s6)
003aab18 3c01006d lui $at, 0x6d
003aab1c 78266940 lq $a2, 26944($at)
003aab20 7ec60160 sq $a2, 352($s6)
003aab24 3c01006d lui $at, 0x6d
003aab28 78266950 lq $a2, 26960($at)
003aab2c 7ec60170 sq $a2, 368($s6)
003aab30 3c01006d lui $at, 0x6d
003aab34 86860030 lh $a2, 0x30($s4)
003aab38 02663021 addu $a2, $s3, $a2
003aab3c 00069c3c dsll32 $s3, $a2, 0x10
003aab40 00139c3f dsra32 $s3, $s3, 0x10
003aab44 00133100 sll $a2, $s3, 4
003aab48 02463025 or $a2, $s2, $a2
003aab4c ac860010 sw $a2, 0x10($a0)
003aab50 8686002c lh $a2, 0x2c($s4)
003aab54 02663021 addu $a2, $s3, $a2
003aab58 00063100 sll $a2, $a2, 4
003aab5c 02263025 or $a2, $s1, $a2
003aab60 ac860020 sw $a2, 0x20($a0)
003aab64 78266920 lq $a2, 26912($at)
003aab68 7ec60180 sq $a2, 384($s6)
003aab6c 3c01006d lui $at, 0x6d
003aab70 78266930 lq $a2, 26928($at)
003aab74 7ec60190 sq $a2, 400($s6)
003aab78 3c01006d lui $at, 0x6d
003aab7c 78266940 lq $a2, 26944($at)
003aab80 7ec601a0 sq $a2, 416($s6)
003aab84 3c01006d lui $at, 0x6d
003aab88 78266950 lq $a2, 26960($at)
003aab8c 7ec601b0 sq $a2, 432($s6)
003aab90 3c01006d lui $at, 0x6d
003aab94 86860030 lh $a2, 0x30($s4)
003aab98 02663021 addu $a2, $s3, $a2
003aab9c 00069c3c dsll32 $s3, $a2, 0x10
003aaba0 00139c3f dsra32 $s3, $s3, 0x10
003aaba4 00133100 sll $a2, $s3, 4
003aaba8 02463025 or $a2, $s2, $a2
003aabac ac860010 sw $a2, 0x10($a0)
003aabb0 8686002c lh $a2, 0x2c($s4)
003aabb4 02663021 addu $a2, $s3, $a2
003aabb8 00063100 sll $a2, $a2, 4
003aabbc 02263025 or $a2, $s1, $a2
003aabc0 ac860020 sw $a2, 0x20($a0)
003aabc4 78266920 lq $a2, 26912($at)
003aabc8 7ec601c0 sq $a2, 448($s6)
003aabcc 3c01006d lui $at, 0x6d
003aabd0 78266930 lq $a2, 26928($at)
003aabd4 7ec601d0 sq $a2, 464($s6)
003aabd8 3c01006d lui $at, 0x6d
003aabdc 78266940 lq $a2, 26944($at)
003aabe0 7ec601e0 sq $a2, 480($s6)
003aabe4 3c01006d lui $at, 0x6d
003aabe8 78266950 lq $a2, 26960($at)
003aabec 7ec601f0 sq $a2, 496($s6)
003aabf0 86860030 lh $a2, 0x30($s4)
003aabf4 26d60200 addiu $s6, $s6, 0x200
003aabf8 02663021 addu $a2, $s3, $a2
003aabfc 00069c3c dsll32 $s3, $a2, 0x10
003aac00 00139c3f dsra32 $s3, $s3, 0x10
003aac04 00133100 sll $a2, $s3, 4
003aac08 02463025 or $a2, $s2, $a2
003aac0c ac860010 sw $a2, 0x10($a0)
003aac10 8686002c lh $a2, 0x2c($s4)
003aac14 02663021 addu $a2, $s3, $a2
003aac18 00063100 sll $a2, $a2, 4
003aac1c 02263025 or $a2, $s1, $a2
003aac20 14a0ff3b bnez $a1, 0x3aa910
003aac24 ac860020 sw $a2, 0x20($a0)
003aac28 0003143c dsll32 $v0, $v1, 0x10
003aac2c 0002143f dsra32 $v0, $v0, 0x10
003aac30 0050082a slt $at, $v0, $s0
003aac34 10200020 beqz $at, 0x3aacb8
003aac38 00000000 nop 
003aac3c 00000000 nop 
003aac40 3c01006d lui $at, 0x6d
003aac44 78256920 lq $a1, 26912($at)
003aac48 24620001 addiu $v0, $v1, 1
003aac4c 00021c3c dsll32 $v1, $v0, 0x10
003aac50 00031c3f dsra32 $v1, $v1, 0x10
003aac54 0070102a slt $v0, $v1, $s0
003aac58 7ec50000 sq $a1, 0($s6)
003aac5c 3c01006d lui $at, 0x6d
003aac60 78256930 lq $a1, 26928($at)
003aac64 7ec50010 sq $a1, 16($s6)
003aac68 3c01006d lui $at, 0x6d
003aac6c 78256940 lq $a1, 26944($at)
003aac70 7ec50020 sq $a1, 32($s6)
003aac74 3c01006d lui $at, 0x6d
003aac78 78256950 lq $a1, 26960($at)
003aac7c 7ec50030 sq $a1, 48($s6)
003aac80 86850030 lh $a1, 0x30($s4)
003aac84 26d60040 addiu $s6, $s6, 0x40
003aac88 02652821 addu $a1, $s3, $a1
003aac8c 00059c3c dsll32 $s3, $a1, 0x10
003aac90 00139c3f dsra32 $s3, $s3, 0x10
003aac94 00132900 sll $a1, $s3, 4
003aac98 02452825 or $a1, $s2, $a1
003aac9c ac850010 sw $a1, 0x10($a0)
003aaca0 8685002c lh $a1, 0x2c($s4)
003aaca4 02652821 addu $a1, $s3, $a1
003aaca8 00052900 sll $a1, $a1, 4
003aacac 02252825 or $a1, $s1, $a1
003aacb0 1440ffe3 bnez $v0, 0x3aac40
003aacb4 ac850020 sw $a1, 0x20($a0)
003aacb8 10000003 b 0x3aacc8
003aacbc 02c0102d move $v0, $s6
003aacc0 0c04ef58 jal 0x13bd60
003aacc4 0000502d move $t2, $zero
003aacc8 dfbf0090 ld $ra, 0x90($sp)
003aaccc 7bbe0080 lq $fp, 128($sp)
003aacd0 7bb70070 lq $s7, 112($sp)
003aacd4 7bb60060 lq $s6, 96($sp)
003aacd8 7bb50050 lq $s5, 80($sp)
003aacdc 7bb40040 lq $s4, 64($sp)
003aace0 7bb30030 lq $s3, 48($sp)
003aace4 7bb20020 lq $s2, 32($sp)
003aace8 7bb10010 lq $s1, 16($sp)
003aacec 7bb00000 lq $s0, 0($sp)
003aacf0 03e00008 jr $ra
003aacf4 27bd00a0 addiu $sp, $sp, 0xa0
; style_table_apply 003aad00..003aad9c
003aad00 00042e3c dsll32 $a1, $a0, 0x18
003aad04 3c030043 lui $v1, 0x43
003aad08 a3848a44 sb $a0, -0x75bc($gp)
003aad0c 00052e3f dsra32 $a1, $a1, 0x18
003aad10 000520c0 sll $a0, $a1, 3
003aad14 2463fbc0 addiu $v1, $v1, -0x440
003aad18 00852021 addu $a0, $a0, $a1
003aad1c 3c010047 lui $at, 0x47
003aad20 00642021 addu $a0, $v1, $a0
003aad24 90830000 lbu $v1, ($a0)
003aad28 a423eb4c sh $v1, -0x14b4($at)
003aad2c 90830000 lbu $v1, ($a0)
003aad30 3c010047 lui $at, 0x47
003aad34 a423eb62 sh $v1, -0x149e($at)
003aad38 90830001 lbu $v1, 1($a0)
003aad3c 3c010047 lui $at, 0x47
003aad40 a023eb54 sb $v1, -0x14ac($at)
003aad44 90830002 lbu $v1, 2($a0)
003aad48 3c010047 lui $at, 0x47
003aad4c a023eb55 sb $v1, -0x14ab($at)
003aad50 90830003 lbu $v1, 3($a0)
003aad54 3c010047 lui $at, 0x47
003aad58 a023eb56 sb $v1, -0x14aa($at)
003aad5c 90830004 lbu $v1, 4($a0)
003aad60 3c010047 lui $at, 0x47
003aad64 a023eb57 sb $v1, -0x14a9($at)
003aad68 90830005 lbu $v1, 5($a0)
003aad6c 3c010047 lui $at, 0x47
003aad70 a023eb58 sb $v1, -0x14a8($at)
003aad74 90830006 lbu $v1, 6($a0)
003aad78 3c010047 lui $at, 0x47
003aad7c a023eb59 sb $v1, -0x14a7($at)
003aad80 90830007 lbu $v1, 7($a0)
003aad84 3c010047 lui $at, 0x47
003aad88 a023eb5a sb $v1, -0x14a6($at)
003aad8c 90830008 lbu $v1, 8($a0)
003aad90 3c010047 lui $at, 0x47
003aad94 03e00008 jr $ra
003aad98 a023eb5b sb $v1, -0x14a5($at)
