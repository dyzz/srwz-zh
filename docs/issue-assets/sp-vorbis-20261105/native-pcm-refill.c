
void FUN_00000c84(void)

{
  int *piVar1;
  uint uVar2;
  int *piVar3;
  int iVar4;
  undefined4 *puVar5;
  uint *puVar6;
  int iVar7;
  int iVar8;
  int iVar9;
  int iVar10;
  int unaff_s5;
  int *piVar11;
  int local_10 [2];
  int local_8 [2];
  
  piVar1 = (int *)0x8;
  piVar3 = local_8;
  piVar11 = piVar3;
  while (piVar11 != (int *)0x0) {
    *(undefined1 *)piVar3 = 0;
    piVar3 = (int *)((int)piVar3 + 1);
    piVar1 = (int *)((int)piVar1 + -1);
    piVar11 = piVar1;
  }
  local_10[0] = DAT_00001250;
  local_10[1] = DAT_00001254;
LAB_00000ce8:
  do {
    do {
      FUN_000011b8(uRam000012a8);
      if ((iRam000012bc == 1) && (unaff_s5 != 0)) {
        unaff_s5 = 0;
        goto LAB_00000d74;
      }
      if ((iRam000012c0 == 1) && (unaff_s5 != 1)) {
        unaff_s5 = 1;
        goto LAB_00000d74;
      }
      if (iRam000012bc == 1) {
        unaff_s5 = 0;
        goto LAB_00000d74;
      }
    } while (iRam000012c0 != 1);
    unaff_s5 = 1;
LAB_00000d74:
    iVar8 = unaff_s5 * 4;
    *(undefined4 *)(iVar8 + 0x12bc) = 0;
    uVar2 = FUN_000011f4((short)unaff_s5,0);
    iVar10 = 1 - (uVar2 >> 0x18);
    if (*(int *)(iVar8 + 0x12b4) == 1) {
      FUN_00000390(unaff_s5,*(undefined4 *)(iVar8 + 0x12d4));
      *(int *)(iVar8 + 0x12b4) = 0;
    }
    if ((*(uint *)(iVar8 + 0x12cc) & 0x8000) == 0) {
      iVar4 = unaff_s5 * 0xc;
      piVar3 = (int *)(iVar8 + 0x12ec);
      iVar7 = *piVar3;
      iVar9 = *(int *)(iVar4 + 0x12fc) - *(int *)(iVar4 + 0x1304);
      piVar1 = (int *)(iVar4 + 0x1304);
      if (iVar7 < iVar9) {
        iVar10 = FUN_000010c8(*(undefined4 *)(iVar8 + 0x12f4),
                              *(int *)(iVar8 + 0x12ac) + iVar10 * iVar7);
        if (iVar10 < *piVar3) goto LAB_00000ce8;
        *piVar1 = *piVar1 + iVar10;
      }
      else {
        piVar11 = (int *)(iVar8 + 0x12ac);
        iVar7 = FUN_000010c8(*(undefined4 *)(iVar8 + 0x12f4),*piVar11 + iVar10 * iVar7,iVar9);
        if (iVar7 < iVar9) goto LAB_00000ce8;
        if ((*(uint *)(iVar8 + 0x12cc) & 0xffff000f) == 0) {
          puVar5 = (undefined4 *)(iVar9 + *piVar11 + iVar10 * *(int *)(iVar8 + 0x12ec));
          iVar10 = 0;
          if (0 < *(int *)(iVar8 + 0x12ec) - iVar9 >> 2) {
            do {
              *puVar5 = 0;
              iVar10 = iVar10 + 1;
              puVar5 = puVar5 + 1;
            } while (iVar10 < *piVar3 - iVar9 >> 2);
          }
          puVar6 = (uint *)(iVar8 + 0x12cc);
          *puVar6 = *puVar6 & 0xfff;
          *puVar6 = *puVar6 | 0x8000;
        }
        else {
          FUN_000010d0(*(undefined4 *)(iVar8 + 0x12f4),*(undefined4 *)(iVar4 + 0x1300),0);
          iVar4 = *(int *)(iVar8 + 0x12ec);
          FUN_000010c8(*(undefined4 *)(iVar8 + 0x12f4),iVar9 + *piVar11 + iVar10 * iVar4,
                       iVar4 - iVar9);
          *piVar1 = *(int *)(iVar8 + 0x12ec) - iVar9;
        }
      }
      if (*(int *)(iVar8 + 0x12c4) == 1) {
        FUN_000009f8(unaff_s5,0);
        FUN_00000390(unaff_s5,0);
        *(int *)(iVar8 + 0x12c4) = 0;
      }
      goto LAB_00000ce8;
    }
    iVar8 = local_8[unaff_s5];
    if (iVar8 < local_10[unaff_s5]) {
      local_8[unaff_s5] = iVar8 + 1;
    }
  } while( true );
}

