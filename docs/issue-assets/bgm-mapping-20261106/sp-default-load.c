
void FUN_00149710(int param_1,int param_2,long param_3)

{
  undefined1 uVar1;
  int *piVar2;
  short *psVar3;
  int *piVar4;
  int iVar5;
  
  if (0x354 < param_2) {
    param_2 = 0x354;
  }
  param_1 = param_1 * 0x118;
  piVar4 = (int *)(param_1 + 0x5b9500);
  *(int *)(param_1 + 0x5b95a8) = param_2 * 0x44 + 0x7b9b10;
  *(undefined1 *)(param_1 + 0x5b9605) = 0;
  *(undefined1 *)(param_1 + 0x5b9606) = 0;
  *(undefined1 *)(param_1 + 0x5b9607) = 0;
  *(undefined1 *)(param_1 + 0x5b9608) = 0;
  *(byte *)(param_1 + 0x5b95c9) = *(byte *)(param_1 + 0x5b95c9) & 0xbf | 0x40;
  *(byte *)(param_1 + 0x5b95c9) = *(byte *)(param_1 + 0x5b95c9) & 0xfe;
  *(undefined4 *)(param_1 + 0x5b95cc) = 0;
  *(undefined2 *)(param_1 + 0x5b95fa) = 0xffff;
  *(undefined4 *)(param_1 + 0x5b95d8) = *(undefined4 *)(param_1 + 0x5b95d4);
  *(undefined2 *)(param_1 + 0x5b95f2) = *(undefined2 *)(param_1 + 0x5b95f0);
  *(undefined1 *)(param_1 + 0x5b9611) = *(undefined1 *)(*(int *)(param_1 + 0x5b95a8) + 0x39);
  thunk_FUN_00293300(piVar4);
  iVar5 = 0;
  psVar3 = (short *)(**(short **)(param_1 + 0x5b95a8) * 0x2a + 0x791e00);
  piVar2 = piVar4;
  do {
    *piVar2 = *psVar3 * 0x28 + 0x79aa00;
    uVar1 = FUN_00149fe0(piVar4,piVar2);
    iVar5 = iVar5 + 1;
    *(undefined1 *)(piVar2 + 1) = uVar1;
    psVar3 = psVar3 + 1;
    piVar2 = piVar2 + 2;
  } while (iVar5 < 0x15);
  if (param_3 != 0) {
    FUN_001496a0(piVar4);
  }
  *(undefined2 *)(param_1 + 0x5b95fc) = 0;
  *(undefined4 *)(param_1 + 0x5b95b0) = 0;
  *(undefined4 *)(param_1 + 0x5b95b4) = 0;
  *(undefined4 *)(param_1 + 0x5b95b8) = 0;
  *(undefined4 *)(param_1 + 0x5b95bc) = 0;
  *(undefined4 *)(param_1 + 0x5b95c0) = 0;
  *(undefined4 *)(param_1 + 0x5b95c4) = 0;
  return;
}

