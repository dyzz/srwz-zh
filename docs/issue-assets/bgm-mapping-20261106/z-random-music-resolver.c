
long FUN_00396d90(long param_1)

{
  int iVar1;
  long lVar2;
  byte *pbVar3;
  byte *pbVar4;
  int iVar5;
  int iVar6;
  byte abStack_e0 [112];
  byte abStack_70 [112];
  
  lVar2 = param_1;
  if (0x65 < param_1) {
    FUN_00182400(0,abStack_70);
    iVar6 = 0;
    pbVar4 = abStack_70;
    for (pbVar3 = pbVar4; *pbVar3 != 0xff; pbVar3 = pbVar3 + 1) {
      iVar6 = iVar6 + 1;
    }
    lVar2 = 0x38;
    if (iVar6 != 0) {
      if (param_1 == 0x66) {
        iVar1 = FUN_0019fa70();
        lVar2 = (long)*(short *)((uint)abStack_70[iVar1 % iVar6] * 0xc + 0x730986);
      }
      else {
        iVar5 = 0;
        iVar1 = 0;
        if (0 < iVar6) {
          pbVar3 = abStack_e0;
          do {
            if ((int)param_1 - 0x67U == (uint)*(byte *)((uint)*pbVar4 * 0xc + 0x730984)) {
              *pbVar3 = *pbVar4;
              iVar5 = iVar5 + 1;
              pbVar3 = pbVar3 + 1;
            }
            iVar1 = iVar1 + 1;
            pbVar4 = pbVar4 + 1;
          } while (iVar1 < iVar6);
        }
        lVar2 = 0x38;
        if (iVar5 != 0) {
          iVar6 = FUN_0019fa70();
          lVar2 = (long)*(short *)((uint)abStack_e0[iVar6 % iVar5] * 0xc + 0x730986);
        }
      }
    }
  }
  return lVar2;
}

