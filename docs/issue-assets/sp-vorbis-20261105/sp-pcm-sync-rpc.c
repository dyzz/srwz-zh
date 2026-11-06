// FUN_0018cb00 entry 0018cb00

undefined4 FUN_0018cb00(ulong param_1,undefined4 param_2)

{
  if ((param_1 & 0xfff0) == 0x8120) {
    FUN_0011f0b0(0x620980,param_1,0,0x620940,0x40,0x620940,0x40,0);
  }
  else {
    uRam00620940 = param_2;
    FUN_0011f0b0(0x620980,param_1,0,0x620940,0x10,0x620940,0x40,0);
  }
  return uRam00620940;
}

